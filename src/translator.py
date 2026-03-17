from __future__ import annotations

import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass

import structlog
from anthropic import AsyncAnthropic

log = structlog.get_logger()

LANGUAGE_NAMES = {
    "ko": "Korean (한국어)",
    "zh-TW": "Traditional Chinese (繁體中文)",
    "en": "English",
}

SYSTEM_PROMPT = """You are a translator in a group chat between a Korean speaker and a Traditional Chinese (繁體中文) speaker.

Rules:
- Output ONLY the translation. No labels, no explanations, no quotation marks.
- Translate naturally and conversationally, matching the tone of the original.
- Use Traditional Chinese (繁體中文), never Simplified Chinese.
- Use conversation context to resolve pronouns, slang, and abbreviations.
- If the message contains mixed languages, translate the entire message to the target language."""

MAX_INPUT_LENGTH = 2000
MAX_CHATS = 100

LANG_LABELS = {
    "ko": "🇰🇷",
    "zh-TW": "🇹🇼",
    "en": "🇺🇸",
}


def _has_translatable_text(text: str) -> bool:
    for ch in text:
        cat = unicodedata.category(ch)
        if cat.startswith("L"):
            return True
    return False


def detect_source_language(text: str) -> str:
    for ch in text:
        cp = ord(ch)
        if 0xAC00 <= cp <= 0xD7AF or 0x3130 <= cp <= 0x318F:
            return "ko"
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            return "zh-TW"
    return "en"


@dataclass
class ContextEntry:
    sender: str
    original: str
    translation: str


class Translator:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_context: int = 20,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_context = max_context
        self._buffers: OrderedDict[int, deque[ContextEntry]] = OrderedDict()

    def _get_buffer(self, chat_id: int) -> deque[ContextEntry]:
        if chat_id in self._buffers:
            self._buffers.move_to_end(chat_id)
        else:
            if len(self._buffers) >= MAX_CHATS:
                self._buffers.popitem(last=False)
            self._buffers[chat_id] = deque(maxlen=self._max_context)
        return self._buffers[chat_id]

    def add_message(
        self, chat_id: int, sender: str, original: str, translation: str
    ) -> None:
        self._get_buffer(chat_id).append(
            ContextEntry(sender=sender, original=original, translation=translation)
        )

    def get_context(self, chat_id: int) -> list[dict[str, str]]:
        return [
            {"sender": e.sender, "original": e.original, "translation": e.translation}
            for e in self._get_buffer(chat_id)
        ]

    def should_skip(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if not _has_translatable_text(stripped):
            return True
        if len(stripped) > MAX_INPUT_LENGTH:
            log.warning("message_too_long", length=len(stripped))
            return True
        return False

    def _build_messages(
        self, chat_id: int, text: str, target_lang: str
    ) -> list[dict[str, str]]:
        lang_name = LANGUAGE_NAMES.get(target_lang, target_lang)
        context_lines = []
        for entry in self._get_buffer(chat_id):
            context_lines.append(
                f"{entry.sender}: {entry.original} → {entry.translation}"
            )

        context_block = "\n".join(context_lines) if context_lines else "(no prior messages)"

        user_content = (
            f"Recent conversation:\n{context_block}\n\n"
            f"Translate the following message to {lang_name}:\n{text}"
        )
        return [{"role": "user", "content": user_content}]

    async def translate(self, chat_id: int, text: str, target_lang: str) -> str | None:
        messages = self._build_messages(chat_id, text, target_lang)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            if not response.content:
                log.warning("empty_api_response", chat_id=chat_id)
                return None
            translation = response.content[0].text.strip()
            source_lang = detect_source_language(text)
            label = LANG_LABELS.get(source_lang, "")
            return f"{label} {translation}" if label else translation
        except Exception:
            log.exception("translation_failed", target_lang=target_lang)
            return None
