import json
import os
from unittest.mock import patch

import pytest

from src.config import load_config


def _env(**overrides: str) -> dict[str, str]:
    base = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "ANTHROPIC_API_KEY": "test-key",
        "ADMIN_USER_ID": "111",
        "USER_MAP": json.dumps({"111": "zh-TW", "222": "ko"}),
    }
    return {**base, **overrides}


class TestLoadConfig:
    def test_loads_valid_config(self):
        with patch.dict(os.environ, _env(), clear=True):
            cfg = load_config()
            assert cfg.telegram_token == "test-token"
            assert cfg.anthropic_api_key == "test-key"
            assert cfg.admin_user_id == "111"
            assert cfg.user_map == {"111": "zh-TW", "222": "ko"}
            assert cfg.claude_model == "claude-haiku-4-5-20251001"

    def test_custom_model(self):
        with patch.dict(os.environ, _env(CLAUDE_MODEL="claude-sonnet-4-5-20250514"), clear=True):
            cfg = load_config()
            assert cfg.claude_model == "claude-sonnet-4-5-20250514"

    def test_missing_token_raises(self):
        env = _env()
        del env["TELEGRAM_BOT_TOKEN"]
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
                load_config()

    def test_missing_api_key_raises(self):
        env = _env()
        del env["ANTHROPIC_API_KEY"]
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                load_config()

    def test_missing_admin_user_id_raises(self):
        env = _env()
        del env["ADMIN_USER_ID"]
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="ADMIN_USER_ID"):
                load_config()

    def test_invalid_user_map_raises(self):
        with patch.dict(os.environ, _env(USER_MAP="not-json"), clear=True):
            with pytest.raises(ValueError, match="USER_MAP"):
                load_config()

    def test_target_language_lookup(self):
        with patch.dict(os.environ, _env(), clear=True):
            cfg = load_config()
            assert cfg.target_language("111") == "zh-TW"
            assert cfg.target_language("222") == "ko"
            assert cfg.target_language("999") is None

    def test_is_admin(self):
        with patch.dict(os.environ, _env(), clear=True):
            cfg = load_config()
            assert cfg.is_admin("111") is True
            assert cfg.is_admin("222") is False
