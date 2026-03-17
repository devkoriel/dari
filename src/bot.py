from __future__ import annotations

import asyncio

import structlog
from telegram import Update
from telegram.ext import (
    Application,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import Config
from src.translator import Translator

log = structlog.get_logger()

MAX_CONCURRENT = 3


def create_app(config: Config) -> Application:
    translator = Translator(
        api_key=config.anthropic_api_key,
        model=config.claude_model,
    )
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

    async def handle_message(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.message
        if message is None or message.text is None or message.from_user is None:
            return

        user_id = str(message.from_user.id)
        sender_name = message.from_user.first_name or "Unknown"
        chat_id = message.chat.id
        text = message.text

        target_lang = config.target_language(user_id)
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

        await message.reply_text(translation)
        log.info(
            "translated",
            sender=sender_name,
            chat_id=chat_id,
            target=target_lang,
            original=text[:50],
            translation=translation[:50],
        )

    app = Application.builder().token(config.telegram_token).build()
    app.add_handler(
        ChatMemberHandler(handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    return app
