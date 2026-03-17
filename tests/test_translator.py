from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.translator import Translator, MAX_INPUT_LENGTH, MAX_CHATS

CHAT_ID = 12345


class TestContextBuffer:
    def test_empty_buffer(self):
        t = Translator(api_key="test", model="test-model")
        assert t.get_context(CHAT_ID) == []

    def test_add_message(self):
        t = Translator(api_key="test", model="test-model")
        t.add_message(chat_id=CHAT_ID, sender="Alice", original="hello", translation="你好")
        ctx = t.get_context(CHAT_ID)
        assert len(ctx) == 1
        assert ctx[0] == {"sender": "Alice", "original": "hello", "translation": "你好"}

    def test_buffer_max_size(self):
        t = Translator(api_key="test", model="test-model", max_context=3)
        for i in range(5):
            t.add_message(chat_id=CHAT_ID, sender="User", original=f"msg{i}", translation=f"tr{i}")
        ctx = t.get_context(CHAT_ID)
        assert len(ctx) == 3
        assert ctx[0]["original"] == "msg2"

    def test_per_chat_isolation(self):
        t = Translator(api_key="test", model="test-model")
        t.add_message(chat_id=1, sender="Alice", original="hello", translation="你好")
        t.add_message(chat_id=2, sender="Bob", original="hi", translation="嗨")
        assert len(t.get_context(1)) == 1
        assert len(t.get_context(2)) == 1
        assert t.get_context(1)[0]["sender"] == "Alice"
        assert t.get_context(2)[0]["sender"] == "Bob"

    def test_lru_eviction(self):
        t = Translator(api_key="test", model="test-model")
        for i in range(MAX_CHATS + 5):
            t.add_message(chat_id=i, sender="User", original=f"msg{i}", translation=f"tr{i}")
        assert len(t._buffers) == MAX_CHATS
        assert 0 not in t._buffers
        assert MAX_CHATS + 4 in t._buffers

    def test_build_prompt_includes_context(self):
        t = Translator(api_key="test", model="test-model")
        t.add_message(chat_id=CHAT_ID, sender="Alice", original="hello", translation="你好")
        messages = t._build_messages(CHAT_ID, "Bob said hi", "ko")
        user_content = messages[0]["content"]
        assert "hello" in user_content
        assert "你好" in user_content
        assert "Bob said hi" in user_content
        assert "Korean" in user_content or "한국어" in user_content

    def test_build_prompt_includes_sender_name(self):
        t = Translator(api_key="test", model="test-model")
        messages = t._build_messages(CHAT_ID, "hello", "ko", sender_name="Jinsoo")
        user_content = messages[0]["content"]
        assert "Jinsoo" in user_content


class TestSameLanguageDetection:
    def test_korean_to_korean_skips(self):
        t = Translator(api_key="test", model="test-model")
        assert t.is_same_language("안녕하세요", "ko") is True

    def test_chinese_to_chinese_skips(self):
        t = Translator(api_key="test", model="test-model")
        assert t.is_same_language("你好嗎", "zh-TW") is True

    def test_english_to_english_skips(self):
        t = Translator(api_key="test", model="test-model")
        assert t.is_same_language("hello world", "en") is True

    def test_korean_to_chinese_translates(self):
        t = Translator(api_key="test", model="test-model")
        assert t.is_same_language("안녕하세요", "zh-TW") is False

    def test_chinese_to_korean_translates(self):
        t = Translator(api_key="test", model="test-model")
        assert t.is_same_language("你好嗎", "ko") is False

    def test_english_to_korean_translates(self):
        t = Translator(api_key="test", model="test-model")
        assert t.is_same_language("hello", "ko") is False


class TestShouldSkip:
    def test_skip_emoji_only(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("😀🎉") is True

    def test_skip_numbers_only(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("12345") is True

    def test_skip_empty(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("") is True
        assert t.should_skip("   ") is True

    def test_skip_too_long(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("a" * (MAX_INPUT_LENGTH + 1)) is True

    def test_no_skip_text(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("hello") is False

    def test_no_skip_short_korean(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("ㅋㅋ") is False

    def test_no_skip_short_chinese(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("哈哈") is False

    def test_no_skip_ok(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("ok") is False

    def test_no_skip_punctuation_with_text(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("ok!!!") is False

    def test_skip_punctuation_only(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("???") is True
        assert t.should_skip("...") is True


class TestTranslate:
    @pytest.mark.asyncio
    async def test_translate_calls_api(self):
        t = Translator(api_key="test", model="test-model")

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="你好世界")]

        with patch.object(t._client, "messages") as mock_messages:
            mock_messages.create = AsyncMock(return_value=mock_response)
            result = await t.translate(CHAT_ID, "hello world", "zh-TW")

        assert result == "🇺🇸 你好世界"
        mock_messages.create.assert_called_once()
        call_kwargs = mock_messages.create.call_args.kwargs
        assert call_kwargs["model"] == "test-model"
        assert call_kwargs["max_tokens"] == 1024

    @pytest.mark.asyncio
    async def test_translate_returns_none_on_api_error(self):
        t = Translator(api_key="test", model="test-model")
        with patch.object(t._client, "messages") as mock_messages:
            mock_messages.create = AsyncMock(side_effect=Exception("API down"))
            result = await t.translate(CHAT_ID, "hello", "zh-TW")
        assert result is None
        assert t.stats["errors"] == 1

    @pytest.mark.asyncio
    async def test_translate_returns_none_on_empty_response(self):
        t = Translator(api_key="test", model="test-model")
        mock_response = MagicMock()
        mock_response.content = []

        with patch.object(t._client, "messages") as mock_messages:
            mock_messages.create = AsyncMock(return_value=mock_response)
            result = await t.translate(CHAT_ID, "hello", "zh-TW")
        assert result is None

    @pytest.mark.asyncio
    async def test_translate_tracks_api_calls(self):
        t = Translator(api_key="test", model="test-model")

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="你好")]

        with patch.object(t._client, "messages") as mock_messages:
            mock_messages.create = AsyncMock(return_value=mock_response)
            await t.translate(CHAT_ID, "hello", "zh-TW")
            await t.translate(CHAT_ID, "world", "zh-TW")

        assert t.stats["api_calls"] == 2


class TestStats:
    def test_initial_stats(self):
        t = Translator(api_key="test", model="test-model")
        assert t.stats["messages"] == 0
        assert t.stats["api_calls"] == 0
        assert t.stats["errors"] == 0
        assert t.stats["skipped_same_lang"] == 0
