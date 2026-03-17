from __future__ import annotations

import asyncio
import datetime
import time

import structlog
from telegram import Update
from telegram.ext import (
    Application,
    CallbackContext,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import Config
from src.quotes import random_quote
from src.storage import JsonStore
from src.transcriber import Transcriber
from src.translator import LANGUAGE_NAMES, Translator, detect_source_language

log = structlog.get_logger()

MAX_CONCURRENT = 3
ERROR_NOTIFY_THRESHOLD = 5
KST = datetime.timezone(datetime.timedelta(hours=9))

LANG_SHORTCUTS = {
    "en": "en",
    "ko": "ko",
    "kr": "ko",
    "zh": "zh-TW",
    "tw": "zh-TW",
    "cn": "zh-TW",
}

SAY_SYSTEM = """You are a language tutor for a Korean-Chinese couple.
Given a word or phrase, explain how to say it in the target language.
Format:
- Translation
- Romanization/pronunciation
- Example sentence in both languages
Keep it short and practical. Use Traditional Chinese (繁體中文) only."""

TEACH_SYSTEM = """You are a cultural language guide for a Korean-Chinese couple.
Explain the given word/concept — its literal meaning, cultural context, when it's used, and the closest equivalent in the other language.
Give 1-2 example sentences. Keep it concise and fun.
Use Traditional Chinese (繁體中文) only. Korean in 반말."""


def create_app(config: Config) -> Application:
    lang_overrides: dict[str, str] = {}
    store = JsonStore(f"{config.data_dir}/bot_data.json")
    translator = Translator(
        api_key=config.anthropic_api_key,
        model=config.claude_model,
    )
    transcriber = Transcriber(groq_api_key=config.groq_api_key)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    start_time = time.monotonic()
    consecutive_errors = 0
    error_notified = False

    # --- Admin gate ---

    async def handle_chat_member(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        member_update = update.my_chat_member
        if member_update is None:
            return

        new_status = member_update.new_chat_member.status
        if new_status not in ("member", "administrator"):
            return

        inviter_id = str(member_update.from_user.id)
        chat_id = member_update.chat.id

        if not config.is_admin(inviter_id):
            log.warning("unauthorized_invite", inviter_id=inviter_id, chat_id=chat_id)
            await context.bot.leave_chat(chat_id)
            return

        log.info("joined_chat", chat_id=chat_id, invited_by=inviter_id)

    # --- /lang command ---

    async def handle_lang(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return

        user_id = str(message.from_user.id)
        if config.target_language(user_id) is None:
            return

        args = context.args
        if not args:
            current = lang_overrides.get(user_id) or config.target_language(user_id)
            lang_name = LANGUAGE_NAMES.get(current, current)
            await message.reply_text(f"Current target: {lang_name}\nUsage: /lang ko | en | zh | reset")
            return

        arg = args[0].lower()
        if arg == "reset":
            lang_overrides.pop(user_id, None)
            default_lang = config.target_language(user_id)
            lang_name = LANGUAGE_NAMES.get(default_lang, default_lang)
            await message.reply_text(f"Reset to default: {lang_name}")
            return

        target = LANG_SHORTCUTS.get(arg)
        if target is None:
            await message.reply_text("Unknown language. Use: /lang ko | en | zh | reset")
            return

        lang_overrides[user_id] = target
        lang_name = LANGUAGE_NAMES.get(target, target)
        await message.reply_text(f"Target language set to: {lang_name}")

    # --- /stats command ---

    async def handle_stats(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return

        user_id = str(message.from_user.id)
        if not config.is_admin(user_id):
            return

        uptime_secs = int(time.monotonic() - start_time)
        hours, remainder = divmod(uptime_secs, 3600)
        minutes, secs = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {secs}s"

        stats = translator.stats
        lines = [
            f"📊 Bot Stats",
            f"Uptime: {uptime_str}",
            f"Translated: {stats['messages']}",
            f"API calls: {stats['api_calls']}",
            f"Errors: {stats['errors']}",
            f"Skipped (same lang): {stats['skipped_same_lang']}",
            f"Active chats: {len(translator._buffers)}",
            "",
        ]

        user_stats = store.get_section("user_stats")
        if user_stats:
            lines.append("👥 Per User:")
            for uid, us in user_stats.items():
                name = us.get("name", uid)
                count = us.get("count", 0)
                lines.append(f"  {name}: {count} messages")

        today = datetime.date.today().isoformat()
        first_today = store.get("first_today", today)
        if first_today:
            lines.append(f"\n🌅 First message today: {first_today}")

        await message.reply_text("\n".join(lines))

    # --- /learn command ---

    async def handle_learn(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return

        user_id = str(message.from_user.id)
        if config.target_language(user_id) is None:
            return

        args = context.args
        if not args:
            current = store.get("learn_mode", user_id, False)
            status = "ON 📖" if current else "OFF"
            await message.reply_text(f"Learn mode: {status}\nUsage: /learn on | off")
            return

        arg = args[0].lower()
        if arg == "on":
            store.set("learn_mode", user_id, True)
            store.save()
            await message.reply_text("📖 Learn mode ON — translations will show original → translation")
        elif arg == "off":
            store.set("learn_mode", user_id, False)
            store.save()
            await message.reply_text("Learn mode OFF — translations only")
        else:
            await message.reply_text("Usage: /learn on | off")

    # --- /say command ---

    async def handle_say(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return

        user_id = str(message.from_user.id)
        if config.target_language(user_id) is None:
            return

        if not context.args:
            await message.reply_text("Usage: /say <word or phrase>\nExample: /say 사랑해")
            return

        phrase = " ".join(context.args)
        source = detect_source_language(phrase)
        if source == "ko":
            target = "Traditional Chinese (繁體中文)"
        elif source == "zh-TW":
            target = "Korean (한국어)"
        else:
            target = "Korean and Traditional Chinese"

        user_msg = f"How do you say '{phrase}' in {target}?"

        async with semaphore:
            result = await translator.ask_claude(SAY_SYSTEM, user_msg, max_tokens=300)

        if result:
            await message.reply_text(f"📝 {result}")
        else:
            await message.reply_text("Sorry, try again later.")

    # --- /teach command ---

    async def handle_teach(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return

        user_id = str(message.from_user.id)
        if config.target_language(user_id) is None:
            return

        if not context.args:
            await message.reply_text("Usage: /teach <word>\nExample: /teach 撒嬌")
            return

        word = " ".join(context.args)
        source = detect_source_language(word)
        if source == "ko":
            lang_hint = "Korean word. Explain in both Korean and Traditional Chinese."
        elif source == "zh-TW":
            lang_hint = "Chinese word. Explain in both Traditional Chinese and Korean."
        else:
            lang_hint = "Explain in both Korean and Traditional Chinese."

        user_msg = f"Explain the word/concept: {word}\n{lang_hint}"

        async with semaphore:
            result = await translator.ask_claude(TEACH_SYSTEM, user_msg, max_tokens=400)

        if result:
            await message.reply_text(f"🎓 {result}")
        else:
            await message.reply_text("Sorry, try again later.")

    # --- /dday command ---

    async def handle_dday(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return

        user_id = str(message.from_user.id)
        if config.target_language(user_id) is None:
            return

        args = context.args or []
        today = datetime.date.today()

        if args and args[0].lower() == "set":
            if len(args) < 2:
                await message.reply_text("Usage: /dday set YYYY-MM-DD [label]\nExample: /dday set 2024-06-15 Anniversary")
                return
            try:
                date = datetime.date.fromisoformat(args[1])
            except ValueError:
                await message.reply_text("Invalid date format. Use YYYY-MM-DD")
                return
            label = " ".join(args[2:]) if len(args) > 2 else "Special Day"
            store.set("dday_dates", label, args[1])
            store.save()
            delta = (today - date).days
            if delta >= 0:
                await message.reply_text(f"💕 Saved! {label}: D+{delta}")
            else:
                await message.reply_text(f"💕 Saved! {label}: D{delta}")
            return

        if args and args[0].lower() == "del":
            label = " ".join(args[1:]) if len(args) > 1 else ""
            if not label:
                await message.reply_text("Usage: /dday del <label>")
                return
            store.delete("dday_dates", label)
            store.save()
            await message.reply_text(f"Deleted: {label}")
            return

        dates = store.get_section("dday_dates")
        if config.anniversary_date and "Anniversary" not in dates:
            dates["Anniversary"] = config.anniversary_date

        if not dates:
            await message.reply_text("No dates set.\nUsage: /dday set YYYY-MM-DD [label]")
            return

        lines = ["💕 D-Day Counter"]
        for label, date_str in sorted(dates.items()):
            try:
                date = datetime.date.fromisoformat(date_str)
                delta = (today - date).days
                if delta >= 0:
                    lines.append(f"  {label}: D+{delta}")
                else:
                    lines.append(f"  {label}: D{delta}")
            except ValueError:
                continue

        await message.reply_text("\n".join(lines))

    # --- Core translation + reply ---

    async def _notify_admin_on_errors(context: ContextTypes.DEFAULT_TYPE) -> None:
        nonlocal error_notified
        if not error_notified:
            try:
                await context.bot.send_message(
                    chat_id=int(config.admin_user_id),
                    text=f"Bot alert: {consecutive_errors} consecutive translation errors. Check logs.",
                )
                error_notified = True
            except Exception:
                log.exception("failed_to_notify_admin")

    async def _translate_and_reply(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        user_id: str,
        sender_name: str,
        text: str,
    ) -> None:
        nonlocal consecutive_errors, error_notified

        target_lang = lang_overrides.get(user_id) or config.target_language(user_id)
        if target_lang is None:
            return

        if translator.should_skip(text):
            return

        if translator.is_same_language(text, target_lang):
            translator.stats["skipped_same_lang"] += 1
            log.debug("skipped_same_language", sender=sender_name, target=target_lang)
            return

        translator.stats["messages"] += 1

        # Track per-user stats
        us = store.get("user_stats", user_id) or {"name": sender_name, "count": 0}
        us["name"] = sender_name
        us["count"] = us.get("count", 0) + 1
        store.set("user_stats", user_id, us)

        today = datetime.date.today().isoformat()
        existing_first = store.get("first_today", today)
        if not existing_first:
            store.set("first_today", today, f"{sender_name} at {datetime.datetime.now(KST).strftime('%H:%M')}")

        if translator.stats["messages"] % 10 == 0:
            store.save()

        async with semaphore:
            translation = await translator.translate(chat_id, text, target_lang, sender_name)

        if translation is None:
            consecutive_errors += 1
            if consecutive_errors >= ERROR_NOTIFY_THRESHOLD:
                await _notify_admin_on_errors(context)
            return

        consecutive_errors = 0
        error_notified = False

        translator.add_message(
            chat_id=chat_id,
            sender=sender_name,
            original=text,
            translation=translation,
        )

        learn_on = store.get("learn_mode", user_id, False)
        if learn_on:
            reply_text = f"{text}\n→ {translation}"
        else:
            reply_text = translation

        await update.message.reply_text(
            reply_text,
            reply_to_message_id=update.message.message_id,
        )
        log.info("translated", sender=sender_name, chat_id=chat_id, target=target_lang)

    # --- Message handlers ---

    async def handle_message(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return

        text = message.text or message.caption
        if not text:
            return

        user_id = str(message.from_user.id)
        sender_name = message.from_user.first_name or "Unknown"
        chat_id = message.chat.id

        await _translate_and_reply(update, context, chat_id, user_id, sender_name, text)

    async def handle_voice(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return

        if not transcriber.enabled:
            return

        user_id = str(message.from_user.id)
        if config.target_language(user_id) is None:
            return

        voice = message.voice or message.audio
        if voice is None:
            return

        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()

        async with semaphore:
            text = await transcriber.transcribe(bytes(audio_bytes))

        if not text:
            return

        sender_name = message.from_user.first_name or "Unknown"
        chat_id = message.chat.id

        await _translate_and_reply(update, context, chat_id, user_id, sender_name, text)

    # --- Daily quote job ---

    async def send_daily_quote(context: CallbackContext) -> None:
        quote = random_quote()
        for uid in config.user_map:
            try:
                await context.bot.send_message(chat_id=int(uid), text=quote)
            except Exception:
                log.exception("daily_quote_send_failed", user_id=uid)

    # --- Build app ---

    app = Application.builder().token(config.telegram_token).build()
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("lang", handle_lang))
    app.add_handler(CommandHandler("stats", handle_stats))
    app.add_handler(CommandHandler("learn", handle_learn))
    app.add_handler(CommandHandler("say", handle_say))
    app.add_handler(CommandHandler("teach", handle_teach))
    app.add_handler(CommandHandler("dday", handle_dday))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            handle_message,
        )
    )
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    # Schedule daily quote
    if app.job_queue is not None:
        quote_time = datetime.time(
            hour=config.daily_quote_hour,
            minute=config.daily_quote_minute,
            tzinfo=KST,
        )
        app.job_queue.run_daily(send_daily_quote, time=quote_time)
        log.info("daily_quote_scheduled", time=quote_time.isoformat())

    return app
