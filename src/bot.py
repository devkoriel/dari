from __future__ import annotations

import asyncio

import structlog
from telegram import Update
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import Config
from src.transcriber import Transcriber
from src.translator import LANGUAGE_NAMES, Translator

log = structlog.get_logger()

MAX_CONCURRENT = 3

LANG_SHORTCUTS = {
    "en": "en",
    "ko": "ko",
    "kr": "ko",
    "zh": "zh-TW",
    "tw": "zh-TW",
    "cn": "zh-TW",
}


def create_app(config: Config) -> Application:
    lang_overrides: dict[str, str] = {}  # user_id -> target_lang override
    translator = Translator(
        api_key=config.anthropic_api_key,
        model=config.claude_model,
    )
    transcriber = Transcriber(groq_api_key=config.groq_api_key)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

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
            log.warning(
                "unauthorized_invite",
                inviter_id=inviter_id,
                chat_id=chat_id,
            )
            await context.bot.leave_chat(chat_id)
            return

        log.info("joined_chat", chat_id=chat_id, invited_by=inviter_id)

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
            await message.reply_text(f"Unknown language. Use: /lang ko | en | zh | reset")
            return

        lang_overrides[user_id] = target
        lang_name = LANGUAGE_NAMES.get(target, target)
        await message.reply_text(f"Target language set to: {lang_name}")

    async def _translate_and_reply(
        update: Update,
        chat_id: int,
        user_id: str,
        sender_name: str,
        text: str,
    ) -> None:
        target_lang = lang_overrides.get(user_id) or config.target_language(user_id)
        if target_lang is None:
            return

        if translator.should_skip(text):
            return

        async with semaphore:
            translation = await translator.translate(chat_id, text, target_lang)

        if translation is None:
            return

        translator.add_message(
            chat_id=chat_id,
            sender=sender_name,
            original=text,
            translation=translation,
        )

        await update.message.reply_text(translation)
        log.info(
            "translated",
            sender=sender_name,
            chat_id=chat_id,
            target=target_lang,
        )

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

        await _translate_and_reply(update, chat_id, user_id, sender_name, text)

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

        await _translate_and_reply(update, chat_id, user_id, sender_name, text)

    app = Application.builder().token(config.telegram_token).build()
    app.add_handler(
        ChatMemberHandler(handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    app.add_handler(CommandHandler("lang", handle_lang))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            handle_message,
        )
    )
    app.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, handle_voice)
    )
    return app
