import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.translator import Translator, MAX_INPUT_LENGTH, MAX_CHATS, PHRASE_TABLE

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

    def test_build_prompt_includes_timestamp(self):
        t = Translator(api_key="test", model="test-model")
        t.add_message(chat_id=CHAT_ID, sender="Alice", original="hello", translation="你好")
        messages = t._build_messages(CHAT_ID, "how are you", "ko")
        user_content = messages[0]["content"]
        assert "just now" in user_content


class TestContextScaling:
    def test_short_message_gets_small_context(self):
        assert Translator._context_size_for_text("ok") == 3

    def test_medium_message_gets_medium_context(self):
        assert Translator._context_size_for_text("오늘 뭐 먹었어?") == 8

    def test_long_message_gets_full_context(self):
        assert Translator._context_size_for_text("This is a much longer message that needs full context to translate properly") == 20

    def test_short_message_limits_context_entries(self):
        t = Translator(api_key="test", model="test-model")
        for i in range(10):
            t.add_message(chat_id=CHAT_ID, sender="User", original=f"msg{i}", translation=f"tr{i}")
        # "ok" is 2 chars → context_size = 3, so only last 3 entries
        messages = t._build_messages(CHAT_ID, "ok", "ko")
        content = messages[0]["content"]
        assert "msg7" in content
        assert "msg8" in content
        assert "msg9" in content
        assert "msg0" not in content

    def test_long_message_uses_full_context(self):
        t = Translator(api_key="test", model="test-model")
        for i in range(10):
            t.add_message(chat_id=CHAT_ID, sender="User", original=f"msg{i}", translation=f"tr{i}")
        messages = t._build_messages(CHAT_ID, "This is a longer sentence that needs context", "ko")
        content = messages[0]["content"]
        assert "msg0" in content
        assert "msg9" in content


class TestFormatAge:
    def test_just_now(self):
        assert Translator._format_age(30) == "just now"

    def test_minutes(self):
        assert Translator._format_age(180) == "3m ago"

    def test_hours(self):
        assert Translator._format_age(7200) == "2h ago"


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


class TestPhraseLookup:
    def test_korean_to_chinese(self):
        t = Translator(api_key="test", model="test-model")
        result = t.lookup_phrase("ㅋㅋㅋ", "zh-TW")
        assert result == "🇰🇷 哈哈哈"
        assert t.stats["phrase_hits"] == 1

    def test_chinese_to_korean(self):
        t = Translator(api_key="test", model="test-model")
        result = t.lookup_phrase("哈哈哈", "ko")
        assert result == "🇹🇼 ㅋㅋㅋ"

    def test_english_case_insensitive(self):
        t = Translator(api_key="test", model="test-model")
        result = t.lookup_phrase("OK", "ko")
        assert result == "🇺🇸 ㅇㅋ"

    def test_strips_whitespace(self):
        t = Translator(api_key="test", model="test-model")
        result = t.lookup_phrase("  고마워  ", "zh-TW")
        assert result == "🇰🇷 謝啦"

    def test_miss_returns_none(self):
        t = Translator(api_key="test", model="test-model")
        result = t.lookup_phrase("이것은 긴 문장입니다", "zh-TW")
        assert result is None
        assert t.stats["phrase_hits"] == 0

    @pytest.mark.asyncio
    async def test_translate_uses_phrase_table(self):
        """translate() should return phrase table result without API call."""
        t = Translator(api_key="test", model="test-model")
        result = await t.translate(CHAT_ID, "사랑해", "zh-TW")
        assert result == "🇰🇷 我愛你"
        assert t.stats["phrase_hits"] == 1
        assert t.stats["api_calls"] == 0


class TestTranslate:
    def _mock_response(self, text, cache_read_tokens=0):
        mock = MagicMock()
        mock.content = [MagicMock(text=text)]
        mock.usage.cache_read_input_tokens = cache_read_tokens
        return mock

    @pytest.mark.asyncio
    async def test_translate_calls_api(self):
        t = Translator(api_key="test", model="test-model")

        with patch.object(t._client, "messages") as mock_messages:
            mock_messages.create = AsyncMock(return_value=self._mock_response("你好世界"))
            result = await t.translate(CHAT_ID, "hello world", "zh-TW")

        assert result == "🇺🇸 你好世界"
        mock_messages.create.assert_called_once()
        call_kwargs = mock_messages.create.call_args.kwargs
        assert call_kwargs["model"] == "test-model"
        assert call_kwargs["max_tokens"] <= 256
        # Verify cached system prompt format
        system = call_kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}

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
        mock_response.usage.cache_read_input_tokens = 0

        with patch.object(t._client, "messages") as mock_messages:
            mock_messages.create = AsyncMock(return_value=mock_response)
            result = await t.translate(CHAT_ID, "hello", "zh-TW")
        assert result is None

    @pytest.mark.asyncio
    async def test_translate_tracks_api_calls(self):
        t = Translator(api_key="test", model="test-model")

        with patch.object(t._client, "messages") as mock_messages:
            mock_messages.create = AsyncMock(return_value=self._mock_response("你好"))
            await t.translate(CHAT_ID, "hello", "zh-TW")
            await t.translate(CHAT_ID, "world", "zh-TW")

        assert t.stats["api_calls"] == 2

    @pytest.mark.asyncio
    async def test_translate_tracks_cache_reads(self):
        t = Translator(api_key="test", model="test-model")

        with patch.object(t._client, "messages") as mock_messages:
            mock_messages.create = AsyncMock(return_value=self._mock_response("你好", cache_read_tokens=150))
            await t.translate(CHAT_ID, "hello", "zh-TW")

        assert t.stats["cache_reads"] == 1


class TestCleanResponse:
    def test_clean_simple(self):
        assert Translator._clean_response("你好") == "你好"

    def test_clean_strips_whitespace(self):
        assert Translator._clean_response("  你好  ") == "你好"

    def test_clean_leaked_reasoning_multiline(self):
        raw = (
            "Wait, I need to translate the message you provided:\n\n"
            "ㅋㅋㅋ 보고싶네\n\n"
            "哈哈哈 我想你了"
        )
        assert Translator._clean_response(raw) == "哈哈哈 我想你了"

    def test_clean_leaked_let_me(self):
        raw = "Let me translate this:\n\n想你了"
        assert Translator._clean_response(raw) == "想你了"

    def test_clean_single_line_preserved(self):
        assert Translator._clean_response("보고싶어") == "보고싶어"

    def test_clean_empty(self):
        assert Translator._clean_response("") == ""

    def test_clean_translation_prefix(self):
        raw = "Translation: 想你了"
        # Single line starting with "translation:" — still returned as-is
        # (the marker detection logs a warning but doesn't alter)
        result = Translator._clean_response(raw)
        assert result == "Translation: 想你了"

    def test_clean_multiline_with_meta_and_original(self):
        raw = (
            "Here is the translation:\n"
            "ㅋㅋㅋ 보고싶네\n"
            "哈哈哈 我想你了"
        )
        # Should skip "Here is..." and the original Korean, take the Chinese
        assert Translator._clean_response(raw) == "哈哈哈 我想你了"


class TestStats:
    def test_initial_stats(self):
        t = Translator(api_key="test", model="test-model")
        assert t.stats["messages"] == 0
        assert t.stats["api_calls"] == 0
        assert t.stats["errors"] == 0
        assert t.stats["skipped_same_lang"] == 0
        assert t.stats["phrase_hits"] == 0
        assert t.stats["cache_reads"] == 0
