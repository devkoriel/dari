from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Config
from src.bot import create_app


@pytest.fixture
def config():
    return Config(
        telegram_token="test-token",
        anthropic_api_key="test-key",
        admin_user_id="111",
        user_map={"111": "zh-TW", "222": "ko"},
        claude_model="test-model",
    )


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_ignores_unknown_user(self, config):
        app = create_app(config)
        handler = app.handlers[0][1]  # index 1 because ChatMemberHandler is 0

        update = MagicMock()
        update.message.from_user.id = 999
        update.message.text = "hello"
        update.message.chat.id = 12345

        context = MagicMock()
        await handler.callback(update, context)
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_emoji_only(self, config):
        app = create_app(config)
        handler = app.handlers[0][1]

        update = MagicMock()
        update.message.from_user.id = 111
        update.message.from_user.first_name = "Test"
        update.message.text = "😀🎉"
        update.message.chat.id = 12345

        context = MagicMock()
        await handler.callback(update, context)
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_none_from_user(self, config):
        app = create_app(config)
        handler = app.handlers[0][1]

        update = MagicMock()
        update.message.from_user = None
        update.message.text = "hello"

        context = MagicMock()
        await handler.callback(update, context)
        update.message.reply_text.assert_not_called()


class TestAdminGate:
    @pytest.mark.asyncio
    async def test_leaves_chat_if_non_admin_invites(self, config):
        app = create_app(config)
        handler = app.handlers[0][0]  # ChatMemberHandler is first

        update = MagicMock()
        update.my_chat_member.from_user.id = 999  # not admin
        update.my_chat_member.chat.id = 12345
        update.my_chat_member.new_chat_member.status = "member"

        context = MagicMock()
        context.bot.leave_chat = AsyncMock()

        await handler.callback(update, context)
        context.bot.leave_chat.assert_called_once_with(12345)

    @pytest.mark.asyncio
    async def test_stays_if_admin_invites(self, config):
        app = create_app(config)
        handler = app.handlers[0][0]

        update = MagicMock()
        update.my_chat_member.from_user.id = 111  # admin
        update.my_chat_member.chat.id = 12345
        update.my_chat_member.new_chat_member.status = "member"

        context = MagicMock()
        context.bot.leave_chat = AsyncMock()

        await handler.callback(update, context)
        context.bot.leave_chat.assert_not_called()
