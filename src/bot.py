from __future__ import annotations

import asyncio
import datetime
import os
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
from src.quotes import random_quote, random_vocabulary
from src.storage import JsonStore
from src.transcriber import Transcriber
from src.translator import LANGUAGE_NAMES, Translator, detect_source_language

log = structlog.get_logger()

MAX_CONCURRENT = 3
ERROR_NOTIFY_THRESHOLD = 5
WATCHDOG_TIMEOUT = 1800  # 30 minutes with no updates → force restart
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
Given a word/phrase, show how to say it in the target language.

Output format (plain text, NO markdown, NO headers, NO bold):
Translation: [translation]
Pronunciation: [romanization]
Example: [one short example sentence]

Keep it to 3-4 lines max. Traditional Chinese (繁體中文) only. Korean in 반말."""

TEACH_SYSTEM = """You are a cultural language guide for a Korean-Chinese couple.
Explain the given word/concept briefly.

Output format (plain text, NO markdown, NO headers, NO bold, NO ---):
[word] = [one-line meaning]
Korean: [Korean explanation, 1 line]
Chinese: [Chinese explanation, 1 line]
Example: [1 example sentence in both languages]

Keep it to 4-6 lines max. Be concise and fun. Traditional Chinese (繁體中文) only. Korean in 반말."""

SUPPORTED_LANGS = {"ko", "zh-TW", "en"}

HELP_TEXT = """🌉 Dari Commands

/lang ko|en|zh|reset — Change translation target
/learn on|off — Show original + pronunciation
/say <phrase> — How to say it in the other language
/teach <word> — Cultural explanation of a word
/tr — Reply to any message to translate it
/dday — Show D-day counter
/dday set YYYY-MM-DD <label> — Add a date
/dday del <label> — Remove a date
/stats — Bot statistics (admin only)
/help — This message

👥 Admin Commands:
/adduser ko|zh|en — Reply to a message to register user
/adduser <id> ko|zh|en — Register by user ID
/removeuser — Reply to remove a user
/removeuser <id> — Remove by user ID
/users — List registered users
/mode couple|friends — Set translation tone for this group

📷 Send a photo to extract & translate text
🎤 Voice messages are transcribed & translated
🎥 Video/video notes are transcribed & translated"""


def create_app(config: Config) -> Application:
    store = JsonStore(f"{config.data_dir}/bot_data.json")
    lang_overrides: dict[str, str] = dict(store.get_section("lang_overrides"))
    translator = Translator(
        api_key=config.anthropic_api_key,
        model=config.claude_model,
    )
    transcriber = Transcriber(groq_api_key=config.groq_api_key)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    start_time = time.monotonic()
    last_activity = time.monotonic()
    consecutive_errors = 0
    error_notified = False
    # Track original message → bot reply for edit support: (chat_id, msg_id) → reply_msg_id
    reply_map: dict[tuple[int, int], int] = {}
    REPLY_MAP_MAX = 500

    # --- Admin gate ---

    async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    # --- /help command ---

    async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None:
            return
        await message.reply_text(HELP_TEXT)

    # --- /lang command ---

    async def handle_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            store.delete("lang_overrides", user_id)
            store.save()
            default_lang = config.target_language(user_id)
            lang_name = LANGUAGE_NAMES.get(default_lang, default_lang)
            await message.reply_text(f"Reset to default: {lang_name}")
            return

        target = LANG_SHORTCUTS.get(arg)
        if target is None:
            await message.reply_text("Unknown language. Use: /lang ko | en | zh | reset")
            return

        lang_overrides[user_id] = target
        store.set("lang_overrides", user_id, target)
        store.save()
        lang_name = LANGUAGE_NAMES.get(target, target)
        await message.reply_text(f"Target language set to: {lang_name}")

    # --- /stats command ---

    async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            "📊 Bot Stats",
            f"Uptime: {uptime_str}",
            f"Translated: {stats['messages']}",
            f"API calls: {stats['api_calls']}",
            f"Phrase hits: {stats['phrase_hits']}",
            f"Cache reads: {stats['cache_reads']}",
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

        first_today = store.get("first_today", "value")
        if first_today and first_today.get("date") == datetime.date.today().isoformat():
            lines.append(f"\n🌅 First message today: {first_today['who']}")

        await message.reply_text("\n".join(lines))

    # --- /learn command ---

    async def handle_learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    async def handle_say(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            result = await translator.ask_claude(SAY_SYSTEM, user_msg, max_tokens=150)

        if result:
            await message.reply_text(f"📝 {result}")
        else:
            await message.reply_text("Sorry, try again later.")

    # --- /teach command ---

    async def handle_teach(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            result = await translator.ask_claude(TEACH_SYSTEM, user_msg, max_tokens=200)

        if result:
            await message.reply_text(f"🎓 {result}")
        else:
            await message.reply_text("Sorry, try again later.")

    # --- /tr command (reply-to-translate) ---

    async def handle_tr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return

        user_id = str(message.from_user.id)
        target_lang = lang_overrides.get(user_id) or config.target_language(user_id)
        if target_lang is None:
            return

        replied = message.reply_to_message
        if replied is None:
            await message.reply_text("Reply to a message with /tr to translate it.")
            return

        text = replied.text or replied.caption
        if not text or translator.should_skip(text):
            await message.reply_text("No translatable text found.")
            return

        async with semaphore:
            translation = await translator.translate(
                message.chat.id, text, target_lang, message.from_user.first_name or "Unknown"
            )

        if translation:
            await replied.reply_text(translation, reply_to_message_id=replied.message_id)
        else:
            await message.reply_text("Translation failed, try again.")

    # --- /dday command ---

    async def handle_dday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
                await message.reply_text(
                    "Usage: /dday set YYYY-MM-DD [label]\nExample: /dday set 2024-06-15 Anniversary"
                )
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
            await message.reply_text("No dates set.\n/dday set YYYY-MM-DD [label]\n/dday del <label>")
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

    # --- /adduser command (admin only) ---

    async def handle_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return
        if not config.is_admin(str(message.from_user.id)):
            return

        args = context.args or []
        reply = message.reply_to_message

        if reply and reply.from_user and args:
            # /adduser <lang> — reply to a message
            target_uid = str(reply.from_user.id)
            target_name = reply.from_user.first_name or str(target_uid)
            lang_arg = args[0].lower()
        elif len(args) >= 2:
            # /adduser <id> <lang>
            target_uid = args[0]
            target_name = target_uid
            lang_arg = args[1].lower()
        else:
            await message.reply_text("Reply to a message with /adduser <ko|zh|en>\nOr: /adduser <user_id> <ko|zh|en>")
            return

        lang = LANG_SHORTCUTS.get(lang_arg)
        if lang is None or lang not in SUPPORTED_LANGS:
            await message.reply_text(f"Unknown language: {lang_arg}\nSupported: ko, zh, en")
            return

        store.set("dynamic_users", target_uid, lang)
        store.save()
        lang_name = LANGUAGE_NAMES.get(lang, lang)
        await message.reply_text(f"✅ Added {target_name} → {lang_name}")
        log.info("user_added", user_id=target_uid, name=target_name, lang=lang)

    # --- /removeuser command (admin only) ---

    async def handle_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return
        if not config.is_admin(str(message.from_user.id)):
            return

        args = context.args or []
        reply = message.reply_to_message

        if reply and reply.from_user:
            target_uid = str(reply.from_user.id)
            target_name = reply.from_user.first_name or target_uid
        elif args:
            target_uid = args[0]
            target_name = target_uid
        else:
            await message.reply_text("Reply to a message with /removeuser\nOr: /removeuser <user_id>")
            return

        if store.get("dynamic_users", target_uid):
            store.delete("dynamic_users", target_uid)
            store.save()
            await message.reply_text(f"✅ Removed {target_name}")
            log.info("user_removed", user_id=target_uid, name=target_name)
        else:
            await message.reply_text(f"User {target_name} not found in dynamic users")

    # --- /users command (admin only) ---

    async def handle_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return
        if not config.is_admin(str(message.from_user.id)):
            return

        lines = ["👥 Registered Users\n"]

        # Static users from config
        for uid, lang in config.user_map.items():
            lang_name = LANGUAGE_NAMES.get(lang, lang)
            us = store.get("user_stats", uid)
            name = us["name"] if us else uid
            lines.append(f"  {name} ({uid}) → {lang_name} [config]")

        # Dynamic users from store
        dynamic = store.get_section("dynamic_users")
        for uid, lang in dynamic.items():
            lang_name = LANGUAGE_NAMES.get(lang, lang)
            us = store.get("user_stats", uid)
            name = us["name"] if us else uid
            lines.append(f"  {name} ({uid}) → {lang_name} [dynamic]")

        if len(lines) == 1:
            lines.append("  No users registered")

        await message.reply_text("\n".join(lines))

    # --- /mode command (admin only) ---

    async def handle_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return
        if not config.is_admin(str(message.from_user.id)):
            return

        chat_id = str(message.chat.id)
        args = context.args or []

        if not args:
            current = store.get("group_modes", chat_id, "couple")
            await message.reply_text(f"Current mode: {current}\nUsage: /mode couple | friends")
            return

        mode = args[0].lower()
        if mode not in ("couple", "friends"):
            await message.reply_text("Unknown mode. Use: /mode couple | friends")
            return

        store.set("group_modes", chat_id, mode)
        store.save()
        desc = "💕 Intimate couple" if mode == "couple" else "👥 Casual friends"
        await message.reply_text(f"Mode set to: {desc}")
        log.info("mode_changed", chat_id=chat_id, mode=mode)

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

    def _track_message_stats(user_id: str, sender_name: str) -> None:
        """Track per-user stats, first-today, and periodic save."""
        translator.stats["messages"] += 1

        us = store.get("user_stats", user_id) or {"name": sender_name, "count": 0}
        us["name"] = sender_name
        us["count"] = us.get("count", 0) + 1
        store.set("user_stats", user_id, us)

        today = datetime.date.today().isoformat()
        existing_first = store.get("first_today", "value")
        if not existing_first or existing_first.get("date") != today:
            store.set(
                "first_today",
                "value",
                {
                    "date": today,
                    "who": f"{sender_name} at {datetime.datetime.now(KST).strftime('%H:%M')}",
                },
            )

        if translator.stats["messages"] % 10 == 0:
            store.save()

    async def _translate_and_reply(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        user_id: str,
        sender_name: str,
        text: str,
    ) -> None:
        nonlocal consecutive_errors, error_notified

        target_lang = (
            lang_overrides.get(user_id) or config.target_language(user_id) or store.get("dynamic_users", user_id)
        )
        if target_lang is None:
            return

        if translator.should_skip(text):
            return

        if translator.is_same_language(text, target_lang):
            translator.stats["skipped_same_lang"] += 1
            log.debug("skipped_same_language", sender=sender_name, target=target_lang)
            return

        _track_message_stats(user_id, sender_name)

        mode = store.get("group_modes", str(chat_id), "couple")
        learn_on = store.get("learn_mode", user_id, False)
        pronunciation = None

        async with semaphore:
            if learn_on and target_lang != "en":
                translation, pronunciation = await translator.translate_learn(
                    chat_id, text, target_lang, sender_name, mode=mode
                )
            else:
                translation = await translator.translate(chat_id, text, target_lang, sender_name, mode=mode)

        if translation is None:
            consecutive_errors += 1
            if consecutive_errors >= ERROR_NOTIFY_THRESHOLD:
                await _notify_admin_on_errors(context)
            await _send_reply(update.message, "⚠️ Translation failed", update.message.message_id)
            return

        if not translation:
            # Empty after cleaning (echo-only) — silently skip, not an error
            return

        consecutive_errors = 0
        error_notified = False

        # Persist group chat ID for daily quote delivery after restarts
        if chat_id < 0 and not store.get("active_groups", str(chat_id)):
            store.set("active_groups", str(chat_id), True)
            store.save()

        translator.add_message(
            chat_id=chat_id,
            sender=sender_name,
            original=text,
            translation=translation,
        )

        if learn_on:
            reply_text = f"{text}\n→ {translation}"
            if pronunciation:
                reply_text += f"\n🗣 {pronunciation}"
        else:
            reply_text = translation

        reply_msg_id = await _send_reply(update.message, reply_text, update.message.message_id)
        if reply_msg_id is not None:
            # Evict oldest entries if map is full
            if len(reply_map) >= REPLY_MAP_MAX:
                oldest = next(iter(reply_map))
                del reply_map[oldest]
            reply_map[(chat_id, update.message.message_id)] = reply_msg_id
        log.info("translated", sender=sender_name, chat_id=chat_id, target=target_lang)

    async def _translate_and_edit(
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        user_id: str,
        sender_name: str,
        text: str,
        message,
    ) -> None:
        """Re-translate an edited message and update the bot's previous reply."""
        key = (chat_id, message.message_id)
        bot_reply_id = reply_map.get(key)
        if bot_reply_id is None:
            return  # No tracked reply to edit

        target_lang = (
            lang_overrides.get(user_id) or config.target_language(user_id) or store.get("dynamic_users", user_id)
        )
        if target_lang is None:
            return

        if translator.should_skip(text):
            return

        if translator.is_same_language(text, target_lang):
            return

        mode = store.get("group_modes", str(chat_id), "couple")
        learn_on = store.get("learn_mode", user_id, False)
        pronunciation = None

        async with semaphore:
            if learn_on and target_lang != "en":
                translation, pronunciation = await translator.translate_learn(
                    chat_id, text, target_lang, sender_name, mode=mode
                )
            else:
                translation = await translator.translate(chat_id, text, target_lang, sender_name, mode=mode)

        if not translation:
            return

        if learn_on:
            reply_text = f"{text}\n→ {translation}"
            if pronunciation:
                reply_text += f"\n🗣 {pronunciation}"
        else:
            reply_text = translation

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=bot_reply_id,
                text=reply_text,
            )
            log.info("edit_translated", sender=sender_name, chat_id=chat_id, target=target_lang)
        except Exception:
            log.exception("edit_message_failed", chat_id=chat_id, msg_id=bot_reply_id)

    # --- Message handlers ---

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        nonlocal last_activity
        last_activity = time.monotonic()

        message = update.message or update.edited_message
        if message is None or message.from_user is None:
            return

        # Skip photo captions — handle_photo deals with photos + captions together
        if message.photo:
            return

        text = message.text or message.caption
        if not text:
            return

        user_id = str(message.from_user.id)
        sender_name = message.from_user.first_name or "Unknown"
        chat_id = message.chat.id

        # Check if this is an edit of a previously translated message
        is_edit = update.edited_message is not None
        if is_edit:
            await _translate_and_edit(context, chat_id, user_id, sender_name, text, message)
        else:
            await _translate_and_reply(update, context, chat_id, user_id, sender_name, text)

    async def _send_reply(message, text: str, reply_to: int | None = None) -> int | None:
        """Send a reply, splitting at newline boundaries for Telegram's 4096 char limit.
        Returns the message_id of the first sent message (for edit tracking)."""
        first_msg_id: int | None = None

        async def _send_with_retry(chunk: str, mid: int | None) -> int | None:
            for attempt in range(3):
                try:
                    sent = await message.reply_text(chunk, reply_to_message_id=mid)
                    return sent.message_id if sent else None
                except Exception:
                    if attempt == 2:
                        log.error("send_reply_failed", attempt=attempt + 1, chunk_len=len(chunk))
                        raise
                    delay = 1.0 * (attempt + 1)
                    log.warning("send_reply_retry", attempt=attempt + 1, delay=delay, chunk_len=len(chunk))
                    await asyncio.sleep(delay)
            return None

        if len(text) <= 4096:
            first_msg_id = await _send_with_retry(text, reply_to)
            return first_msg_id

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in text.split("\n"):
            # +1 for the newline separator
            added_len = len(line) + (1 if current else 0)
            if current_len + added_len > 4096 and current:
                chunks.append("\n".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += added_len
        if current:
            chunks.append("\n".join(current))

        for i, chunk in enumerate(chunks):
            mid = reply_to if i == 0 else None
            sent_id = await _send_with_retry(chunk, mid)
            if i == 0:
                first_msg_id = sent_id
        return first_msg_id

    async def _transcribe_and_reply(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        file_id: str,
        user_id: str,
        icon: str,
        filename: str = "voice.ogg",
    ) -> None:
        nonlocal consecutive_errors, error_notified

        message = update.message
        if message is None or message.from_user is None:
            return

        target_lang = (
            lang_overrides.get(user_id) or config.target_language(user_id) or store.get("dynamic_users", user_id)
        )
        if target_lang is None:
            return

        file = await context.bot.get_file(file_id)

        if file.file_size and file.file_size > 20 * 1024 * 1024:
            log.warning("media_too_large", size=file.file_size)
            return

        audio_bytes = await file.download_as_bytearray()

        async with semaphore:
            text = await transcriber.transcribe(bytes(audio_bytes), filename=filename)

        if not text or translator.should_skip(text):
            return

        sender_name = message.from_user.first_name or "Unknown"
        chat_id = message.chat.id

        if translator.is_same_language(text, target_lang):
            translator.stats["skipped_same_lang"] += 1
            await _send_reply(message, f"{icon} {text}", message.message_id)
            return

        _track_message_stats(user_id, sender_name)

        learn_on = store.get("learn_mode", user_id, False)
        pronunciation = None

        async with semaphore:
            if learn_on and target_lang != "en":
                translation, pronunciation = await translator.translate_learn(chat_id, text, target_lang, sender_name)
            else:
                translation = await translator.translate(chat_id, text, target_lang, sender_name)

        if translation is None:
            consecutive_errors += 1
            if consecutive_errors >= ERROR_NOTIFY_THRESHOLD:
                await _notify_admin_on_errors(context)
            await _send_reply(message, f"{icon} {text}", message.message_id)
            return

        consecutive_errors = 0
        error_notified = False

        translator.add_message(
            chat_id=chat_id,
            sender=sender_name,
            original=text,
            translation=translation,
        )

        reply_text = f"{icon} {text}\n→ {translation}"
        if pronunciation:
            reply_text += f"\n🗣 {pronunciation}"
        await _send_reply(message, reply_text, message.message_id)
        log.info("media_translated", sender=sender_name, chat_id=chat_id, type=icon)

    async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        nonlocal last_activity
        last_activity = time.monotonic()

        message = update.message
        if message is None or message.from_user is None:
            return

        if not transcriber.enabled:
            return

        user_id = str(message.from_user.id)
        voice = message.voice or message.audio
        if voice is None:
            return

        await _transcribe_and_reply(update, context, voice.file_id, user_id, "🎤")

    async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        nonlocal last_activity
        last_activity = time.monotonic()

        message = update.message
        if message is None or message.from_user is None:
            return

        if not transcriber.enabled:
            return

        user_id = str(message.from_user.id)

        video_note = message.video_note
        if video_note is not None:
            await _transcribe_and_reply(update, context, video_note.file_id, user_id, "🎥", filename="video.mp4")
            return

        video = message.video
        if video is not None:
            await _transcribe_and_reply(update, context, video.file_id, user_id, "🎬", filename="video.mp4")

    # --- Photo handler (image translation) ---

    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        nonlocal last_activity
        last_activity = time.monotonic()

        message = update.message
        if message is None or message.from_user is None:
            return
        if not message.photo:
            return

        user_id = str(message.from_user.id)
        target_lang = (
            lang_overrides.get(user_id) or config.target_language(user_id) or store.get("dynamic_users", user_id)
        )
        if target_lang is None:
            return

        # Extract and translate text from the image itself
        photo = message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()

        async with semaphore:
            result = await translator.translate_image(bytes(image_bytes), "image/jpeg", target_lang)

        if result is not None:
            await message.reply_text(result, reply_to_message_id=message.message_id)
            sender_name = message.from_user.first_name or "Unknown"
            translator.add_message(
                chat_id=message.chat.id,
                sender=sender_name,
                original="[photo]",
                translation=result,
            )

        # Also translate the caption if present
        caption = message.caption
        if caption:
            sender_name = message.from_user.first_name or "Unknown"
            await _translate_and_reply(update, context, message.chat.id, user_id, sender_name, caption)

    # --- Daily quote job ---

    async def send_daily_quote(context: CallbackContext) -> None:
        quote = random_quote()
        vocab = random_vocabulary()
        text = f"{quote}\n\n{vocab}"
        # Collect group chat IDs from both in-memory buffers and persistent store
        group_ids: set[int] = set()
        for chat_id in translator._buffers:
            if chat_id < 0:
                group_ids.add(chat_id)
        for chat_id_str in store.get_section("active_groups"):
            group_ids.add(int(chat_id_str))

        sent = False
        for chat_id in group_ids:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
                sent = True
            except Exception:
                log.warning("daily_quote_send_failed", chat_id=chat_id)
        if not sent:
            for uid in config.user_map:
                try:
                    await context.bot.send_message(chat_id=int(uid), text=text)
                except Exception:
                    log.warning("daily_quote_send_failed", user_id=uid)

    # --- Watchdog: force exit if polling stalls (polling mode only) ---

    async def watchdog_check(context: CallbackContext) -> None:
        idle = time.monotonic() - last_activity
        if idle > WATCHDOG_TIMEOUT:
            log.error("watchdog_triggered", idle_seconds=int(idle))
            store.save()
            os._exit(1)  # Hard exit — launchd KeepAlive restarts us

    # --- Error handler ---

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("unhandled_error", error=str(context.error), exc_info=context.error)

    # --- Build app ---

    async def on_shutdown(_app: Application) -> None:
        store.save()
        await transcriber.close()
        log.info("shutdown_save_complete")

    app = (
        Application.builder()
        .token(config.telegram_token)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(15)
        .pool_timeout(15)
        .build()
    )
    app.add_error_handler(on_error)
    app.post_shutdown = on_shutdown
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("lang", handle_lang))
    app.add_handler(CommandHandler("stats", handle_stats))
    app.add_handler(CommandHandler("learn", handle_learn))
    app.add_handler(CommandHandler("say", handle_say))
    app.add_handler(CommandHandler("teach", handle_teach))
    app.add_handler(CommandHandler("tr", handle_tr))
    app.add_handler(CommandHandler("dday", handle_dday))
    app.add_handler(CommandHandler("adduser", handle_adduser))
    app.add_handler(CommandHandler("removeuser", handle_removeuser))
    app.add_handler(CommandHandler("users", handle_users))
    app.add_handler(CommandHandler("mode", handle_mode))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND & filters.UpdateType.MESSAGE,
            handle_message,
        )
    )
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND & filters.UpdateType.EDITED_MESSAGE,
            handle_message,
        )
    )
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE | filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Register commands with Telegram so they appear in the command menu
    async def post_init(application: Application) -> None:
        from telegram import BotCommand

        await application.bot.set_my_commands(
            [
                BotCommand("help", "Show all commands"),
                BotCommand("lang", "Change translation target language"),
                BotCommand("learn", "Toggle learn mode (original + pronunciation)"),
                BotCommand("say", "How to say a phrase in the other language"),
                BotCommand("teach", "Cultural explanation of a word"),
                BotCommand("tr", "Reply to translate a specific message"),
                BotCommand("dday", "D-day counter"),
                BotCommand("adduser", "Register a user for translation (admin)"),
                BotCommand("removeuser", "Remove a user (admin)"),
                BotCommand("users", "List registered users (admin)"),
                BotCommand("mode", "Set translation tone: couple/friends (admin)"),
                BotCommand("stats", "Bot statistics (admin)"),
            ]
        )

    app.post_init = post_init

    # Schedule daily quote
    if app.job_queue is not None:
        quote_time = datetime.time(
            hour=config.daily_quote_hour,
            minute=config.daily_quote_minute,
            tzinfo=KST,
        )
        app.job_queue.run_daily(send_daily_quote, time=quote_time)
        log.info("daily_quote_scheduled", time=quote_time.isoformat())
        if not config.webhook_url:
            app.job_queue.run_repeating(watchdog_check, interval=300, first=300)
            log.info("watchdog_enabled", timeout_seconds=WATCHDOG_TIMEOUT)

    return app
