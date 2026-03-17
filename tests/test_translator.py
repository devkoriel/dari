from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.translator import Translator


class TestContextBuffer:
    def test_empty_buffer(self):
        t = Translator(api_key="test", model="test-model")
        assert t.get_context() == []

    def test_add_message(self):
        t = Translator(api_key="test", model="test-model")
        t.add_message(sender="Alice", original="hello", translation="你好")
        ctx = t.get_context()
        assert len(ctx) == 1
        assert ctx[0] == {"sender": "Alice", "original": "hello", "translation": "你好"}

    def test_buffer_max_size(self):
        t = Translator(api_key="test", model="test-model", max_context=3)
        for i in range(5):
            t.add_message(sender="User", original=f"msg{i}", translation=f"tr{i}")
        ctx = t.get_context()
        assert len(ctx) == 3
        assert ctx[0]["original"] == "msg2"

    def test_build_prompt_includes_context(self):
        t = Translator(api_key="test", model="test-model")
        t.add_message(sender="Alice", original="hello", translation="你好")
        messages = t._build_messages("Bob said hi", "ko")
        user_content = messages[0]["content"]
        assert "hello" in user_content
        assert "你好" in user_content
        assert "Bob said hi" in user_content
        assert "Korean" in user_content or "한국어" in user_content


class TestShouldSkip:
    def test_skip_emoji_only(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("😀🎉") is True

    def test_skip_numbers_only(self):
        t = Translator(api_key="test", model="test-model")
        assert t.should_skip("12345") is True

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


class TestTranslate:
    @pytest.mark.asyncio
    async def test_translate_calls_api(self):
        t = Translator(api_key="test", model="test-model")

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="你好世界")]

        with patch.object(t._client, "messages") as mock_messages:
            mock_messages.create = AsyncMock(return_value=mock_response)
            result = await t.translate("hello world", "zh-TW")

        assert result == "你好世界"
        mock_messages.create.assert_called_once()
        call_kwargs = mock_messages.create.call_args.kwargs
        assert call_kwargs["model"] == "test-model"
        assert call_kwargs["max_tokens"] == 1024

    @pytest.mark.asyncio
    async def test_translate_returns_none_on_skip(self):
        t = Translator(api_key="test", model="test-model")
        result = await t.translate("😀🎉", "zh-TW")
        assert result is None

    @pytest.mark.asyncio
    async def test_translate_returns_none_on_api_error(self):
        t = Translator(api_key="test", model="test-model")
        with patch.object(t._client, "messages") as mock_messages:
            mock_messages.create = AsyncMock(side_effect=Exception("API down"))
            result = await t.translate("hello", "zh-TW")
        assert result is None
