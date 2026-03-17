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


def _make_text_update(user_id: int, text: str, chat_id: int = 12345, first_name: str = "Test"):
    update = MagicMock()
    update.message.from_user.id = user_id
    update.message.from_user.first_name = first_name
    update.message.text = text
    update.message.caption = None
    update.message.chat.id = chat_id
    update.message.reply_text = AsyncMock()
    return update


def _make_caption_update(user_id: int, caption: str, chat_id: int = 12345, first_name: str = "Test"):
    update = MagicMock()
    update.message.from_user.id = user_id
    update.message.from_user.first_name = first_name
    update.message.text = None
    update.message.caption = caption
    update.message.chat.id = chat_id
    update.message.reply_text = AsyncMock()
    return update


class TestHandleMessage:
    def _get_message_handler(self, config):
        app = create_app(config)
        # Handlers: [0]=ChatMemberHandler, [1]=CommandHandler(/lang), [2]=MessageHandler(text), [3]=MessageHandler(voice)
        return app.handlers[0][2]

    @pytest.mark.asyncio
    async def test_ignores_unknown_user(self, config):
        handler = self._get_message_handler(config)
        update = _make_text_update(user_id=999, text="hello")
        await handler.callback(update, MagicMock())
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_emoji_only(self, config):
        handler = self._get_message_handler(config)
        update = _make_text_update(user_id=111, text="😀🎉")
        await handler.callback(update, MagicMock())
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_none_from_user(self, config):
        handler = self._get_message_handler(config)
        update = MagicMock()
        update.message.from_user = None
        update.message.text = "hello"
        await handler.callback(update, MagicMock())
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_translates_known_user(self, config):
        handler = self._get_message_handler(config)
        update = _make_text_update(user_id=111, text="안녕하세요", first_name="Koriel")

        with patch("src.bot.Translator.translate", new_callable=AsyncMock, return_value="🇰🇷 你好"):
            await handler.callback(update, MagicMock())

        update.message.reply_text.assert_called_once_with("🇰🇷 你好")

    @pytest.mark.asyncio
    async def test_translates_photo_caption(self, config):
        handler = self._get_message_handler(config)
        update = _make_caption_update(user_id=222, caption="好漂亮", first_name="GF")

        with patch("src.bot.Translator.translate", new_callable=AsyncMock, return_value="🇹🇼 예쁘다"):
            await handler.callback(update, MagicMock())

        update.message.reply_text.assert_called_once_with("🇹🇼 예쁘다")

    @pytest.mark.asyncio
    async def test_no_reply_when_translation_none(self, config):
        handler = self._get_message_handler(config)
        update = _make_text_update(user_id=111, text="hello")

        with patch("src.bot.Translator.translate", new_callable=AsyncMock, return_value=None):
            await handler.callback(update, MagicMock())

        update.message.reply_text.assert_not_called()


class TestAdminGate:
    def _get_member_handler(self, config):
        app = create_app(config)
        return app.handlers[0][0]  # ChatMemberHandler is always first

    @pytest.mark.asyncio
    async def test_leaves_chat_if_non_admin_invites(self, config):
        handler = self._get_member_handler(config)

        update = MagicMock()
        update.my_chat_member.from_user.id = 999
        update.my_chat_member.chat.id = 12345
        update.my_chat_member.new_chat_member.status = "member"

        context = MagicMock()
        context.bot.leave_chat = AsyncMock()

        await handler.callback(update, context)
        context.bot.leave_chat.assert_called_once_with(12345)

    @pytest.mark.asyncio
    async def test_stays_if_admin_invites(self, config):
        handler = self._get_member_handler(config)

        update = MagicMock()
        update.my_chat_member.from_user.id = 111
        update.my_chat_member.chat.id = 12345
        update.my_chat_member.new_chat_member.status = "member"

        context = MagicMock()
        context.bot.leave_chat = AsyncMock()

        await handler.callback(update, context)
        context.bot.leave_chat.assert_not_called()
