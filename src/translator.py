from __future__ import annotations

import unicodedata
from collections import deque
from dataclasses import dataclass

import structlog
from anthropic import AsyncAnthropic

log = structlog.get_logger()

LANGUAGE_NAMES = {
    "ko": "Korean (한국어)",
    "zh-TW": "Traditional Chinese (繁體中文)",
}

SYSTEM_PROMPT = """You are a translator in a group chat between a Korean speaker and a Traditional Chinese (繁體中文) speaker.

Rules:
- Output ONLY the translation. No labels, no explanations, no quotation marks.
- Translate naturally and conversationally, matching the tone of the original.
- Use Traditional Chinese (繁體中文), never Simplified Chinese.
- Use conversation context to resolve pronouns, slang, and abbreviations.
- If the message contains mixed languages, translate the entire message to the target language."""


def _is_emoji_only(text: str) -> bool:
    for ch in text:
        cat = unicodedata.category(ch)
        if cat.startswith("L") or cat.startswith("N"):
            return False
    return True


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
        self._buffer: deque[ContextEntry] = deque(maxlen=max_context)

    def add_message(
        self, sender: str, original: str, translation: str
    ) -> None:
        self._buffer.append(
            ContextEntry(sender=sender, original=original, translation=translation)
        )

    def get_context(self) -> list[dict[str, str]]:
        return [
            {"sender": e.sender, "original": e.original, "translation": e.translation}
            for e in self._buffer
        ]

    def should_skip(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if stripped.isdigit():
            return True
        if _is_emoji_only(stripped):
            return True
        return False

    def _build_messages(
        self, text: str, target_lang: str
    ) -> list[dict[str, str]]:
        lang_name = LANGUAGE_NAMES.get(target_lang, target_lang)
        context_lines = []
        for entry in self._buffer:
            context_lines.append(
                f"{entry.sender}: {entry.original} → {entry.translation}"
            )

        context_block = "\n".join(context_lines) if context_lines else "(no prior messages)"

        user_content = (
            f"Recent conversation:\n{context_block}\n\n"
            f"Translate the following message to {lang_name}:\n{text}"
        )
        return [{"role": "user", "content": user_content}]

    async def translate(self, text: str, target_lang: str) -> str | None:
        if self.should_skip(text):
            return None

        messages = self._build_messages(text, target_lang)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            return response.content[0].text.strip()
        except Exception:
            log.exception("translation_failed", target_lang=target_lang)
            return None
