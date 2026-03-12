"""Conversation history manager for Gaming Assistant."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from .const import DEFAULT_HISTORY_SIZE, IMAGE_DEDUP_WINDOW_SECONDS

_LOGGER = logging.getLogger(__name__)


class HistoryManager:
    """Stores and loads tip history per game/client.

    Storage: {config_dir}/gaming_assistant/history/{game_or_client_id}.json
    """

    def __init__(self, config_dir: str, max_entries: int = DEFAULT_HISTORY_SIZE) -> None:
        self._base_path = Path(config_dir) / "gaming_assistant" / "history"
        self._max_entries = max_entries
        self._cache: dict[str, dict] = {}

    def _ensure_dir(self) -> None:
        self._base_path.mkdir(parents=True, exist_ok=True)

    def _file_path(self, key: str) -> Path:
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key.lower())
        return self._base_path / f"{safe_key}.json"

    def _load(self, key: str) -> dict:
        if key in self._cache:
            return self._cache[key]

        path = self._file_path(key)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._cache[key] = data
                return data
            except (json.JSONDecodeError, OSError) as err:
                _LOGGER.warning(
                    "Corrupt history file %s, recreating: %s", path, err
                )

        data = {
            "game": key,
            "entries": [],
            "metadata": {
                "total_tips": 0,
                "first_session": None,
                "last_session": None,
            },
        }
        self._cache[key] = data
        return data

    def _save(self, key: str) -> None:
        self._ensure_dir()
        data = self._cache.get(key)
        if data is None:
            return
        path = self._file_path(key)
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as err:
            _LOGGER.error("Failed to save history %s: %s", path, err)

    async def add_entry(
        self, game: str, client_id: str, image_hash: str, tip: str
    ) -> None:
        key = game or client_id
        data = self._load(key)
        now = datetime.now().isoformat(timespec="seconds")

        data["entries"].append({
            "timestamp": now,
            "image_hash": image_hash,
            "tip": tip,
            "client_id": client_id,
        })

        # Trim to max entries
        if len(data["entries"]) > self._max_entries:
            data["entries"] = data["entries"][-self._max_entries:]

        data["metadata"]["total_tips"] = data["metadata"].get("total_tips", 0) + 1
        if data["metadata"]["first_session"] is None:
            data["metadata"]["first_session"] = now
        data["metadata"]["last_session"] = now

        self._save(key)

    async def get_recent(self, key: str, count: int = 5) -> list[dict]:
        data = self._load(key)
        return data["entries"][-count:]

    async def is_duplicate_image(self, image_hash: str, key: str | None = None) -> bool:
        """Check if the same image was processed within the dedup window."""
        now = time.time()
        keys = [key] if key else list(self._cache.keys())

        for k in keys:
            data = self._load(k)
            for entry in reversed(data["entries"]):
                if entry["image_hash"] == image_hash:
                    try:
                        entry_time = datetime.fromisoformat(entry["timestamp"]).timestamp()
                        if now - entry_time < IMAGE_DEDUP_WINDOW_SECONDS:
                            return True
                    except (ValueError, OSError):
                        pass
                    break  # Only check most recent match per key
        return False

    async def clear(self, key: str | None = None) -> None:
        if key:
            self._cache.pop(key, None)
            path = self._file_path(key)
            if path.exists():
                path.unlink()
        else:
            self._cache.clear()
            if self._base_path.exists():
                for f in self._base_path.glob("*.json"):
                    f.unlink()

    @staticmethod
    def format_for_prompt(entries: list[dict]) -> str:
        if not entries:
            return ""
        lines = [f"  {i}. {e['tip']}" for i, e in enumerate(entries, 1)]
        return (
            "\n\nPrevious tips this session (oldest first):\n"
            + "\n".join(lines)
            + "\n\nDo NOT repeat any of these tips. Give a NEW insight."
        )
