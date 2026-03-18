from __future__ import annotations

import base64
import time
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass, field

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

CONTEXT USAGE:
- You receive recent conversation history for tone and flow ONLY.
- ALWAYS translate the CURRENT message based on its own meaning first. Context helps with ambiguity, NOT to override the literal meaning.
- Example: if context mentions "work hard" but the current message says "it's working now", translate as "functioning/running" NOT "laboring". The current message stands on its own.

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

# Instant lookup table for common phrases — no API call needed.
# key: (normalized_text, target_lang) → translation (without flag prefix)
PHRASE_TABLE: dict[tuple[str, str], str] = {
    # Korean → Chinese
    ("ㅋㅋ", "zh-TW"): "哈哈",
    ("ㅋㅋㅋ", "zh-TW"): "哈哈哈",
    ("ㅋㅋㅋㅋ", "zh-TW"): "哈哈哈哈",
    ("ㅋㅋㅋㅋㅋ", "zh-TW"): "哈哈哈哈哈",
    ("ㅠㅠ", "zh-TW"): "嗚嗚",
    ("ㅠㅠㅠ", "zh-TW"): "嗚嗚嗚",
    ("ㅎㅎ", "zh-TW"): "呵呵",
    ("ㅎㅎㅎ", "zh-TW"): "呵呵呵",
    ("ㄱㅅ", "zh-TW"): "謝啦",
    ("ㄴㄴ", "zh-TW"): "不不",
    ("ㅇㅇ", "zh-TW"): "嗯嗯",
    ("ㅇㅋ", "zh-TW"): "好",
    ("ㄷㄷ", "zh-TW"): "抖抖",
    ("고마워", "zh-TW"): "謝啦",
    ("고마워!", "zh-TW"): "謝啦！",
    ("고마워요", "zh-TW"): "謝謝",
    ("사랑해", "zh-TW"): "我愛你",
    ("사랑해!", "zh-TW"): "我愛你！",
    ("보고싶어", "zh-TW"): "想你了",
    ("보고싶다", "zh-TW"): "想你了",
    ("보고싶어!", "zh-TW"): "想你了！",
    ("보고싶네", "zh-TW"): "想你了呢",
    ("뭐해", "zh-TW"): "你在幹嘛",
    ("뭐해?", "zh-TW"): "你在幹嘛？",
    ("밥 먹었어?", "zh-TW"): "吃飯了嗎？",
    ("밥먹었어?", "zh-TW"): "吃飯了嗎？",
    ("잘자", "zh-TW"): "晚安",
    ("잘자!", "zh-TW"): "晚安！",
    ("좋아", "zh-TW"): "好",
    ("좋아!", "zh-TW"): "好！",
    ("알겠어", "zh-TW"): "知道了",
    ("응", "zh-TW"): "嗯",
    ("응응", "zh-TW"): "嗯嗯",
    ("아니", "zh-TW"): "不是",
    ("진짜?", "zh-TW"): "真的嗎？",
    ("진짜", "zh-TW"): "真的",
    ("대박", "zh-TW"): "太厲害了",
    ("대박!", "zh-TW"): "太厲害了！",
    ("아하", "zh-TW"): "啊哈",
    ("ㅇㅈ", "zh-TW"): "認同",
    ("ㅁㅊ", "zh-TW"): "瘋了",
    ("귀여워", "zh-TW"): "好可愛",
    ("귀여워!", "zh-TW"): "好可愛！",
    ("화이팅", "zh-TW"): "加油",
    ("화이팅!", "zh-TW"): "加油！",
    ("아이고", "zh-TW"): "唉呀",
    ("헐", "zh-TW"): "天啊",
    # Korean → English
    ("ㅋㅋ", "en"): "haha",
    ("ㅋㅋㅋ", "en"): "hahaha",
    ("ㅠㅠ", "en"): "T_T",
    ("고마워", "en"): "thanks",
    ("사랑해", "en"): "I love you",
    # Chinese → Korean
    ("哈哈", "ko"): "ㅋㅋ",
    ("哈哈哈", "ko"): "ㅋㅋㅋ",
    ("哈哈哈哈", "ko"): "ㅋㅋㅋㅋ",
    ("嗚嗚", "ko"): "ㅠㅠ",
    ("嗚嗚嗚", "ko"): "ㅠㅠㅠ",
    ("呵呵", "ko"): "ㅎㅎ",
    ("謝謝", "ko"): "고마워",
    ("謝謝!", "ko"): "고마워!",
    ("謝謝！", "ko"): "고마워!",
    ("謝啦", "ko"): "고마워",
    ("我愛你", "ko"): "사랑해",
    ("想你了", "ko"): "보고싶어",
    ("想你", "ko"): "보고싶어",
    ("你在幹嘛", "ko"): "뭐해",
    ("你在幹嘛？", "ko"): "뭐해?",
    ("在幹嘛", "ko"): "뭐해",
    ("吃飯了嗎", "ko"): "밥 먹었어?",
    ("吃飯了嗎？", "ko"): "밥 먹었어?",
    ("晚安", "ko"): "잘자",
    ("晚安!", "ko"): "잘자!",
    ("晚安！", "ko"): "잘자!",
    ("好", "ko"): "좋아",
    ("好!", "ko"): "좋아!",
    ("好！", "ko"): "좋아!",
    ("好的", "ko"): "알겠어",
    ("知道了", "ko"): "알겠어",
    ("嗯", "ko"): "응",
    ("嗯嗯", "ko"): "응응",
    ("不是", "ko"): "아니",
    ("真的嗎", "ko"): "진짜?",
    ("真的嗎？", "ko"): "진짜?",
    ("真的", "ko"): "진짜",
    ("太厲害了", "ko"): "대박",
    ("好可愛", "ko"): "귀여워",
    ("好可愛!", "ko"): "귀여워!",
    ("好可愛！", "ko"): "귀여워!",
    ("加油", "ko"): "화이팅",
    ("加油!", "ko"): "화이팅!",
    ("加油！", "ko"): "화이팅!",
    ("天啊", "ko"): "헐",
    ("哦", "ko"): "아",
    ("喔", "ko"): "아",
    ("啊哈", "ko"): "아하",
    # Chinese → English
    ("哈哈", "en"): "haha",
    ("哈哈哈", "en"): "hahaha",
    ("謝謝", "en"): "thanks",
    ("我愛你", "en"): "I love you",
    # English → Korean
    ("ok", "ko"): "ㅇㅋ",
    ("okay", "ko"): "ㅇㅋ",
    ("lol", "ko"): "ㅋㅋ",
    ("haha", "ko"): "ㅋㅋ",
    ("thanks", "ko"): "고마워",
    ("thank you", "ko"): "고마워",
    # English → Chinese
    ("ok", "zh-TW"): "好",
    ("okay", "zh-TW"): "好",
    ("lol", "zh-TW"): "哈哈",
    ("haha", "zh-TW"): "哈哈",
    ("thanks", "zh-TW"): "謝啦",
    ("thank you", "zh-TW"): "謝謝",
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
    timestamp: float = field(default_factory=time.monotonic)


class Translator:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_context: int = 20,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key, timeout=30.0)
        self._model = model
        self._max_context = max_context
        self._buffers: OrderedDict[int, deque[ContextEntry]] = OrderedDict()
        self.stats: dict[str, int] = {
            "messages": 0, "api_calls": 0, "errors": 0,
            "skipped_same_lang": 0, "phrase_hits": 0, "cache_reads": 0,
        }

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

    def get_context(self, chat_id: int) -> list[dict]:
        return [
            {"sender": e.sender, "original": e.original, "translation": e.translation}
            for e in self._get_buffer(chat_id)
        ]

    def is_same_language(self, text: str, target_lang: str) -> bool:
        source = detect_source_language(text)
        if target_lang == "zh-TW":
            return source == "zh-TW"
        return source == target_lang

    def lookup_phrase(self, text: str, target_lang: str) -> str | None:
        """Try instant lookup for common phrases. Returns full flagged translation or None."""
        normalized = text.strip()
        result = PHRASE_TABLE.get((normalized, target_lang))
        if result is None:
            # Try lowercase for English
            result = PHRASE_TABLE.get((normalized.lower(), target_lang))
        if result is not None:
            self.stats["phrase_hits"] += 1
            source_lang = detect_source_language(text)
            label = LANG_LABELS.get(source_lang, "")
            return f"{label} {result}" if label else result
        return None

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

    @staticmethod
    def _context_size_for_text(text: str) -> int:
        """Scale context window based on message complexity."""
        length = len(text.strip())
        if length <= 5:
            return 3
        if length <= 20:
            return 8
        return 20

    @staticmethod
    def _format_age(seconds: float) -> str:
        """Human-readable age like '2m ago' or 'just now'."""
        if seconds < 60:
            return "just now"
        minutes = int(seconds / 60)
        if minutes < 60:
            return f"{minutes}m ago"
        hours = int(minutes / 60)
        return f"{hours}h ago"

    def _build_messages(
        self, chat_id: int, text: str, target_lang: str, sender_name: str = ""
    ) -> list[dict[str, str]]:
        lang_name = LANGUAGE_NAMES.get(target_lang, target_lang)
        now = time.monotonic()

        # Scale how much context to include based on message complexity
        max_entries = self._context_size_for_text(text)
        buffer = list(self._get_buffer(chat_id))
        recent = buffer[-max_entries:] if buffer else []

        context_lines = []
        for entry in recent:
            age = self._format_age(now - entry.timestamp)
            context_lines.append(
                f"[{age}] {entry.sender}: {entry.original} → {entry.translation}"
            )

        context_block = "\n".join(context_lines) if context_lines else "(no prior messages)"

        sender_info = f" (from {sender_name})" if sender_name else ""
        user_content = (
            f"Recent conversation:\n{context_block}\n\n"
            f"Translate the following message{sender_info} to {lang_name}:\n{text}"
        )
        return [{"role": "user", "content": user_content}]

    async def translate_image(
        self, image_bytes: bytes, media_type: str, target_lang: str
    ) -> str | None:
        self.stats["api_calls"] += 1
        lang_name = LANGUAGE_NAMES.get(target_lang, target_lang)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(image_bytes).decode(),
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f"Extract ALL text from this image. Then translate it to {lang_name}.\n\n"
                                "Format:\n📷 [original text]\n→ [translation]\n\n"
                                "If no text found, reply: No text found."
                            ),
                        },
                    ],
                }],
            )
            if not response.content:
                return None
            return response.content[0].text.strip()
        except Exception:
            self.stats["errors"] += 1
            log.exception("image_translation_failed")
            return None

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

        leak_markers = (
            "wait,", "let me", "i need to", "i should", "translation:", "here is",
            "the translation", "translating", "note:", "sorry",
        )

        lines = text.split("\n")
        if len(lines) > 1:
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
                text = candidates[-1]
            else:
                text = lines[0].strip()

        lower = text.lower()
        strip_prefixes = ("translation:", "here is the translation:", "the translation is:")
        for prefix in strip_prefixes:
            if lower.startswith(prefix):
                text = text[len(prefix):].strip()
                log.warning("leaked_reasoning_stripped", raw=raw[:200])
                break

        return text

    async def translate(
        self, chat_id: int, text: str, target_lang: str, sender_name: str = ""
    ) -> str | None:
        # Try instant phrase lookup first
        quick = self.lookup_phrase(text, target_lang)
        if quick is not None:
            return quick

        self.stats["api_calls"] += 1
        messages = self._build_messages(chat_id, text, target_lang, sender_name)

        # Scale max_tokens to input length
        max_tokens = min(256, max(64, len(text) * 4))

        # Use prompt caching for the system prompt
        cached_system = [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=cached_system,
                messages=messages,
            )

            # Track cache usage
            usage = response.usage
            if hasattr(usage, "cache_read_input_tokens") and usage.cache_read_input_tokens:
                self.stats["cache_reads"] += 1

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
