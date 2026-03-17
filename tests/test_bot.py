from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Config


@pytest.fixture
def config():
    return Config(
        telegram_token="test-token",
        anthropic_api_key="test-key",
        user_map={"111": "zh-TW", "222": "ko"},
        claude_model="test-model",
    )


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_ignores_unknown_user(self, config):
        from src.bot import create_app

        app = create_app(config)
        handler = app.handlers[0][0]

        update = MagicMock()
        update.message.from_user.id = 999
        update.message.text = "hello"

        context = MagicMock()
        await handler.callback(update, context)
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_emoji_only(self, config):
        from src.bot import create_app

        app = create_app(config)
        handler = app.handlers[0][0]

        update = MagicMock()
        update.message.from_user.id = 111
        update.message.from_user.first_name = "Test"
        update.message.text = "😀🎉"

        context = MagicMock()
        await handler.callback(update, context)
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_none_from_user(self, config):
        from src.bot import create_app

        app = create_app(config)
        handler = app.handlers[0][0]

        update = MagicMock()
        update.message.from_user = None
        update.message.text = "hello"

        context = MagicMock()
        await handler.callback(update, context)
        update.message.reply_text.assert_not_called()
