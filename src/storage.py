from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_DEFAULT_DATA: dict[str, Any] = {
    "dday_dates": {},
    "learn_mode": {},
    "user_stats": {},
    "lang_overrides": {},
}


class JsonStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {k: dict(v) if isinstance(v, dict) else v for k, v in _DEFAULT_DATA.items()}
        try:
            with open(self._path) as f:
                data = json.load(f)
            for key, default in _DEFAULT_DATA.items():
                if key not in data:
                    data[key] = dict(default) if isinstance(default, dict) else default
            return data
        except (json.JSONDecodeError, OSError):
            log.exception("storage_load_failed", path=str(self._path))
            return {k: dict(v) if isinstance(v, dict) else v for k, v in _DEFAULT_DATA.items()}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except OSError:
            log.exception("storage_save_failed", path=str(self._path))
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self._data.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any) -> None:
        if section not in self._data:
            self._data[section] = {}
        self._data[section][key] = value

    def get_section(self, section: str) -> dict[str, Any]:
        return dict(self._data.get(section, {}))

    def delete(self, section: str, key: str) -> None:
        if section in self._data:
            self._data[section].pop(key, None)
