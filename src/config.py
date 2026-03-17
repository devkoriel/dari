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

    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    return Config(
        telegram_token=token,
        anthropic_api_key=api_key,
        user_map=user_map,
        admin_user_id=admin_user_id,
        claude_model=model,
    )
