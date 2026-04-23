"""Persistent settings stored as JSON alongside the SQLite database."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any

from .config import DEFAULT_SETTINGS, SETTINGS_PATH

log = logging.getLogger(__name__)


class Settings:
    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._data: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._save_locked()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                merged = dict(DEFAULT_SETTINGS)
                merged.update(raw)
                self._data = merged
        except (json.JSONDecodeError, OSError):
            log.warning("settings file unreadable, resetting to defaults", exc_info=True)
            self._save_locked()

    def _save_locked(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save_locked()

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._data.update(changes)
            self._save_locked()
            return dict(self._data)
