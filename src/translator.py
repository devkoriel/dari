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

SYSTEM_PROMPT = """You are a translation engine. You receive a message and output ONLY its translation. Nothing else.

ABSOLUTE RULES:
1. Output ONLY the translated text. ONE line. No thinking, no explanations, no "let me translate", no commentary.
2. NEVER output the original text. NEVER repeat the input. NEVER add quotation marks.
3. If you catch yourself writing anything other than the translation, STOP. Delete it. Output only the translation.

CONTEXT: This is a casual couple's chat between Jinsoo (Korean) and 敏甄 (Traditional Chinese/繁體中文).

TONE:
- This is an intimate couple — use casual, warm language. NEVER use formal/polite forms.
- Korean: always use 반말 (e.g., 보고싶어, 뭐해, 고마워). Never 존댓말.
- Chinese: use casual spoken Taiwanese Mandarin (e.g., 謝啦 not 謝謝您, 想你了 not 我想念你). Drop 你 when natural.
- Traditional Chinese (繁體中文) ONLY. Never Simplified.
- Match emotional energy: cute→cute, playful→playful, ㅋㅋ→哈哈, ㅠㅠ→嗚嗚, 哈哈哈→ㅋㅋㅋ
- Short messages get short translations. 고마워! → 謝啦！ not 非常感謝你！"""

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
    ko_count = 0
    zh_count = 0
    for ch in text:
        cp = ord(ch)
        if 0xAC00 <= cp <= 0xD7AF or 0x3130 <= cp <= 0x318F:
            ko_count += 1
        elif 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            zh_count += 1
    if ko_count > 0 and ko_count >= zh_count:
        return "ko"
    if zh_count > 0:
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
        self.stats: dict[str, int] = {"messages": 0, "api_calls": 0, "errors": 0, "skipped_same_lang": 0}

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

    def is_same_language(self, text: str, target_lang: str) -> bool:
        source = detect_source_language(text)
        if target_lang == "zh-TW":
            return source == "zh-TW"
        return source == target_lang

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
        self, chat_id: int, text: str, target_lang: str, sender_name: str = ""
    ) -> list[dict[str, str]]:
        lang_name = LANGUAGE_NAMES.get(target_lang, target_lang)
        context_lines = []
        for entry in self._get_buffer(chat_id):
            context_lines.append(
                f"{entry.sender}: {entry.original} → {entry.translation}"
            )

        context_block = "\n".join(context_lines) if context_lines else "(no prior messages)"

        sender_info = f" (from {sender_name})" if sender_name else ""
        user_content = (
            f"Recent conversation:\n{context_block}\n\n"
            f"Translate the following message{sender_info} to {lang_name}:\n{text}"
        )
        return [{"role": "user", "content": user_content}]

    async def ask_claude(self, system: str, user_msg: str, max_tokens: int = 512) -> str | None:
        self.stats["api_calls"] += 1
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            if not response.content:
                return None
            return response.content[0].text.strip()
        except Exception:
            self.stats["errors"] += 1
            log.exception("ask_claude_failed")
            return None

    @staticmethod
    def _clean_response(raw: str) -> str:
        """Strip any leaked reasoning or meta-text from Claude's response."""
        text = raw.strip()
        if not text:
            return text

        # If response has multiple lines, Claude may have leaked reasoning.
        # Common patterns: "Wait, I need to...", "Let me translate...", "Translation:"
        leak_markers = (
            "wait,", "let me", "i need to", "i should", "translation:", "here is",
            "the translation", "translating", "note:", "sorry",
        )

        lines = text.split("\n")
        if len(lines) > 1:
            # Try to find the actual translation — usually the last non-empty line
            # that doesn't look like meta-text
            candidates = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                lower = stripped.lower()
                if any(lower.startswith(m) for m in leak_markers):
                    continue
                if "translate" in lower and "message" in lower:
                    continue
                candidates.append(stripped)

            if candidates:
                # Prefer the last candidate (Claude usually puts the real answer last)
                text = candidates[-1]
            else:
                # Fallback: just take the first line
                text = lines[0].strip()

        # Strip leading meta-text on a single line
        lower = text.lower()
        for marker in leak_markers:
            if lower.startswith(marker):
                # Likely not a translation at all, but try to salvage
                log.warning("leaked_reasoning_detected", raw=raw[:200])
                break

        return text

    async def translate(
        self, chat_id: int, text: str, target_lang: str, sender_name: str = ""
    ) -> str | None:
        self.stats["api_calls"] += 1
        messages = self._build_messages(chat_id, text, target_lang, sender_name)

        # Scale max_tokens to input length — short messages need short translations
        max_tokens = min(256, max(64, len(text) * 4))

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            if not response.content:
                log.warning("empty_api_response", chat_id=chat_id)
                return None
            raw = response.content[0].text.strip()
            translation = self._clean_response(raw)
            if not translation:
                log.warning("empty_after_cleaning", chat_id=chat_id, raw=raw[:200])
                return None
            source_lang = detect_source_language(text)
            label = LANG_LABELS.get(source_lang, "")
            return f"{label} {translation}" if label else translation
        except Exception:
            self.stats["errors"] += 1
            log.exception("translation_failed", target_lang=target_lang)
            return None
