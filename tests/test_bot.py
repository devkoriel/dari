from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.ext import CommandHandler, MessageHandler

from src.bot import create_app
from src.config import Config


@pytest.fixture
def config():
    return Config(
        telegram_token="test-token",
        anthropic_api_key="test-key",
        admin_user_id="111",
        user_map={"111": "zh-TW", "222": "ko"},
        claude_model="test-model",
    )


def _find_handler(app, command=None, handler_type=None):
    for group_handlers in app.handlers.values():
        for h in group_handlers:
            if command and isinstance(h, CommandHandler) and command in h.commands:
                return h
            if handler_type and isinstance(h, handler_type) and not isinstance(h, CommandHandler):
                return h
    return None


def _find_message_handler(app):
    """Find the text/caption MessageHandler (not voice)."""
    for group_handlers in app.handlers.values():
        for h in group_handlers:
            if isinstance(h, MessageHandler) and not isinstance(h, CommandHandler):
                # The text handler callback is named handle_message
                if h.callback.__name__ == "handle_message":
                    return h
    return None


def _make_text_update(user_id: int, text: str, chat_id: int = 12345, first_name: str = "Test"):
    update = MagicMock()
    update.message.from_user.id = user_id
    update.message.from_user.first_name = first_name
    update.message.text = text
    update.message.caption = None
    update.message.photo = None
    update.message.chat.id = chat_id
    update.message.message_id = 42
    update.message.reply_text = AsyncMock()
    return update


def _make_caption_update(user_id: int, caption: str, chat_id: int = 12345, first_name: str = "Test"):
    update = MagicMock()
    update.message.from_user.id = user_id
    update.message.from_user.first_name = first_name
    update.message.text = None
    update.message.caption = caption
    update.message.photo = None
    update.message.chat.id = chat_id
    update.message.message_id = 43
    update.message.reply_text = AsyncMock()
    return update


def _make_command_update(user_id: int, args: list[str] | None = None, first_name: str = "Test"):
    update = MagicMock()
    update.message.from_user.id = user_id
    update.message.from_user.first_name = first_name
    update.message.chat.id = 12345
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args or []
    return update, context


class TestHandleMessage:
    def _get_handler(self, config):
        app = create_app(config)
        return _find_message_handler(app)

    @pytest.mark.asyncio
    async def test_ignores_unknown_user(self, config):
        handler = self._get_handler(config)
        update = _make_text_update(user_id=999, text="hello")
        await handler.callback(update, MagicMock())
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_emoji_only(self, config):
        handler = self._get_handler(config)
        update = _make_text_update(user_id=111, text="😀🎉")
        await handler.callback(update, MagicMock())
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_none_from_user(self, config):
        handler = self._get_handler(config)
        update = MagicMock()
        update.message.from_user = None
        update.message.text = "hello"
        await handler.callback(update, MagicMock())
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_translates_known_user(self, config):
        handler = self._get_handler(config)
        update = _make_text_update(user_id=111, text="안녕하세요", first_name="Koriel")

        with patch("src.bot.Translator.translate", new_callable=AsyncMock, return_value="🇰🇷 你好"):
            with patch("src.bot.Translator.is_same_language", return_value=False):
                await handler.callback(update, MagicMock())

        update.message.reply_text.assert_called_once_with("🇰🇷 你好", reply_to_message_id=42)

    @pytest.mark.asyncio
    async def test_translates_photo_caption(self, config):
        handler = self._get_handler(config)
        update = _make_caption_update(user_id=222, caption="好漂亮", first_name="GF")

        with patch("src.bot.Translator.translate", new_callable=AsyncMock, return_value="🇹🇼 예쁘다"):
            with patch("src.bot.Translator.is_same_language", return_value=False):
                await handler.callback(update, MagicMock())

        update.message.reply_text.assert_called_once_with("🇹🇼 예쁘다", reply_to_message_id=43)

    @pytest.mark.asyncio
    async def test_shows_warning_when_translation_none(self, config):
        handler = self._get_handler(config)
        update = _make_text_update(user_id=111, text="hello")

        with patch("src.bot.Translator.translate", new_callable=AsyncMock, return_value=None):
            with patch("src.bot.Translator.is_same_language", return_value=False):
                await handler.callback(update, MagicMock())

        update.message.reply_text.assert_called_once_with("⚠️ Translation failed", reply_to_message_id=42)

    @pytest.mark.asyncio
    async def test_skips_same_language(self, config):
        handler = self._get_handler(config)
        update = _make_text_update(user_id=111, text="你好嗎")

        with patch("src.bot.Translator.translate", new_callable=AsyncMock) as mock_translate:
            await handler.callback(update, MagicMock())

        mock_translate.assert_not_called()
        update.message.reply_text.assert_not_called()


class TestAdminGate:
    def _get_handler(self, config):
        app = create_app(config)
        return app.handlers[0][0]

    @pytest.mark.asyncio
    async def test_leaves_chat_if_non_admin_invites(self, config):
        handler = self._get_handler(config)

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
        handler = self._get_handler(config)

        update = MagicMock()
        update.my_chat_member.from_user.id = 111
        update.my_chat_member.chat.id = 12345
        update.my_chat_member.new_chat_member.status = "member"

        context = MagicMock()
        context.bot.leave_chat = AsyncMock()

        await handler.callback(update, context)
        context.bot.leave_chat.assert_not_called()


class TestLearnMode:
    def _get_handler(self, config):
        app = create_app(config)
        return _find_handler(app, command="learn")

    @pytest.mark.asyncio
    async def test_learn_on(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=["on"])
        await handler.callback(update, context)
        update.message.reply_text.assert_called_once()
        assert "ON" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_learn_off(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=["off"])
        await handler.callback(update, context)
        update.message.reply_text.assert_called_once()
        assert "OFF" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_learn_no_args_shows_status(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=[])
        await handler.callback(update, context)
        update.message.reply_text.assert_called_once()
        assert "Learn mode" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_learn_ignores_unknown_user(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=999, args=["on"])
        await handler.callback(update, context)
        update.message.reply_text.assert_not_called()


class TestSayCommand:
    def _get_handler(self, config):
        app = create_app(config)
        return _find_handler(app, command="say")

    @pytest.mark.asyncio
    async def test_say_no_args(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=[])
        await handler.callback(update, context)
        assert "Usage" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_say_with_phrase(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=["사랑해"])

        with patch("src.bot.Translator.ask_claude", new_callable=AsyncMock, return_value="我愛你 (wǒ ài nǐ)"):
            await handler.callback(update, context)

        assert "我愛你" in update.message.reply_text.call_args[0][0]


class TestTeachCommand:
    def _get_handler(self, config):
        app = create_app(config)
        return _find_handler(app, command="teach")

    @pytest.mark.asyncio
    async def test_teach_no_args(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=[])
        await handler.callback(update, context)
        assert "Usage" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_teach_with_word(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=["撒嬌"])

        with patch("src.bot.Translator.ask_claude", new_callable=AsyncMock, return_value="撒嬌 means..."):
            await handler.callback(update, context)

        assert "撒嬌" in update.message.reply_text.call_args[0][0]


class TestDDay:
    def _get_handler(self, config, tmp_path):
        cfg = Config(
            telegram_token=config.telegram_token,
            anthropic_api_key=config.anthropic_api_key,
            admin_user_id=config.admin_user_id,
            user_map=config.user_map,
            claude_model=config.claude_model,
            data_dir=str(tmp_path),
        )
        app = create_app(cfg)
        return _find_handler(app, command="dday")

    @pytest.mark.asyncio
    async def test_dday_no_dates(self, config, tmp_path):
        handler = self._get_handler(config, tmp_path)
        update, context = _make_command_update(user_id=111, args=[])
        await handler.callback(update, context)
        assert "No dates" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_dday_set(self, config, tmp_path):
        handler = self._get_handler(config, tmp_path)
        update, context = _make_command_update(user_id=111, args=["set", "2024-06-15", "Anniversary"])
        await handler.callback(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "Anniversary" in reply
        assert "D+" in reply

    @pytest.mark.asyncio
    async def test_dday_invalid_date(self, config, tmp_path):
        handler = self._get_handler(config, tmp_path)
        update, context = _make_command_update(user_id=111, args=["set", "not-a-date"])
        await handler.callback(update, context)
        assert "Invalid" in update.message.reply_text.call_args[0][0]


class TestAddUser:
    def _get_handler(self, config):
        app = create_app(config)
        return _find_handler(app, command="adduser")

    @pytest.mark.asyncio
    async def test_adduser_by_reply(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=["ko"])
        # Simulate replying to a message from user 333
        replied_msg = MagicMock()
        replied_msg.from_user.id = 333
        replied_msg.from_user.first_name = "Friend"
        update.message.reply_to_message = replied_msg
        await handler.callback(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "Friend" in reply
        assert "Korean" in reply

    @pytest.mark.asyncio
    async def test_adduser_by_id(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=["444", "zh"])
        update.message.reply_to_message = None
        await handler.callback(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "444" in reply
        assert "Chinese" in reply

    @pytest.mark.asyncio
    async def test_adduser_non_admin_ignored(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=999, args=["ko"])
        await handler.callback(update, context)
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_adduser_invalid_lang(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=["555", "xyz"])
        update.message.reply_to_message = None
        await handler.callback(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "Unknown" in reply


class TestRemoveUser:
    def _get_handler(self, config):
        app = create_app(config)
        return _find_handler(app, command="removeuser")

    @pytest.mark.asyncio
    async def test_removeuser_not_found(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=["999"])
        update.message.reply_to_message = None
        await handler.callback(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "not found" in reply


class TestMode:
    def _get_handler(self, config):
        app = create_app(config)
        return _find_handler(app, command="mode")

    @pytest.mark.asyncio
    async def test_mode_set_friends(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=["friends"])
        await handler.callback(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "friends" in reply.lower() or "Casual" in reply

    @pytest.mark.asyncio
    async def test_mode_invalid(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=["invalid"])
        await handler.callback(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "Unknown" in reply

    @pytest.mark.asyncio
    async def test_mode_no_args_shows_current(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111, args=[])
        await handler.callback(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "couple" in reply


class TestUsers:
    def _get_handler(self, config):
        app = create_app(config)
        return _find_handler(app, command="users")

    @pytest.mark.asyncio
    async def test_users_lists_config_users(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=111)
        await handler.callback(update, context)
        reply = update.message.reply_text.call_args[0][0]
        assert "config" in reply.lower()

    @pytest.mark.asyncio
    async def test_users_non_admin_ignored(self, config):
        handler = self._get_handler(config)
        update, context = _make_command_update(user_id=999)
        await handler.callback(update, context)
        update.message.reply_text.assert_not_called()
