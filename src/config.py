from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    telegram_token: str
    anthropic_api_key: str
    user_map: dict[str, str]
    admin_user_id: str
    claude_model: str = "claude-haiku-4-5-20251001"
    groq_api_key: str = ""
    data_dir: str = "data"
    daily_quote_hour: int = 9
    daily_quote_minute: int = 0
    anniversary_date: str = ""

    def target_language(self, user_id: str) -> str | None:
        return self.user_map.get(user_id)

    def is_admin(self, user_id: str) -> bool:
        return user_id == self.admin_user_id


def load_config() -> Config:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required")

    admin_user_id = os.environ.get("ADMIN_USER_ID")
    if not admin_user_id:
        raise ValueError("ADMIN_USER_ID is required")

    user_map_raw = os.environ.get("USER_MAP", "{}")
    try:
        user_map = json.loads(user_map_raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"USER_MAP must be valid JSON: {e}") from e

    if not isinstance(user_map, dict):
        raise ValueError("USER_MAP must be a JSON object")

    supported_languages = {"ko", "zh-TW", "en"}
    for uid, lang in user_map.items():
        if lang not in supported_languages:
            raise ValueError(f"Unsupported language '{lang}' for user {uid}. Supported: {supported_languages}")

    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    groq_api_key = os.environ.get("GROQ_API_KEY", "")
    data_dir = os.environ.get("DATA_DIR", "data")
    raw_hour = os.environ.get("DAILY_QUOTE_HOUR", "9")
    raw_minute = os.environ.get("DAILY_QUOTE_MINUTE", "0")
    try:
        daily_quote_hour = int(raw_hour)
    except ValueError:
        raise ValueError(f"DAILY_QUOTE_HOUR must be an integer, got '{raw_hour}'")
    try:
        daily_quote_minute = int(raw_minute)
    except ValueError:
        raise ValueError(f"DAILY_QUOTE_MINUTE must be an integer, got '{raw_minute}'")
    if not (0 <= daily_quote_hour <= 23):
        raise ValueError(f"DAILY_QUOTE_HOUR must be 0-23, got {daily_quote_hour}")
    if not (0 <= daily_quote_minute <= 59):
        raise ValueError(f"DAILY_QUOTE_MINUTE must be 0-59, got {daily_quote_minute}")
    anniversary_date = os.environ.get("ANNIVERSARY_DATE", "")

    return Config(
        telegram_token=token,
        anthropic_api_key=api_key,
        user_map=user_map,
        admin_user_id=admin_user_id,
        claude_model=model,
        groq_api_key=groq_api_key,
        data_dir=data_dir,
        daily_quote_hour=daily_quote_hour,
        daily_quote_minute=daily_quote_minute,
        anniversary_date=anniversary_date,
    )
