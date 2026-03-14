"""Conversation history manager for Gaming Assistant.

Storage format: JSON Lines (one entry per line) in
{config_dir}/gaming_assistant/history/{game_or_client_id}.jsonl

Append-only for normal writes; full rewrite only during cleanup.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from .const import DEFAULT_HISTORY_SIZE, IMAGE_DEDUP_WINDOW_SECONDS

_LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 30


class HistoryManager:
    """Stores and loads tip history per game/client using JSONL files."""

    def __init__(
        self,
        config_dir: str,
        max_entries: int = DEFAULT_HISTORY_SIZE,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    ) -> None:
        self._base_path = Path(config_dir) / "gaming_assistant" / "history"
        self._max_entries = max_entries
        self._max_age_days = max_age_days
        self._cache: dict[str, list[dict]] = {}

    def _ensure_dir(self) -> None:
        self._base_path.mkdir(parents=True, exist_ok=True)

    def _file_path(self, key: str) -> Path:
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key.lower())
        return self._base_path / f"{safe_key}.jsonl"

    def _load(self, key: str) -> list[dict]:
        if key in self._cache:
            return self._cache[key]

        path = self._file_path(key)
        entries: list[dict] = []
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entries.append(json.loads(line))
                            except json.JSONDecodeError:
                                _LOGGER.debug("Skipping corrupt line in %s", path)
            except OSError as err:
                _LOGGER.warning("Failed to read history %s: %s", path, err)

        self._cache[key] = entries
        return entries

    async def add_entry(
        self, game: str, client_id: str, image_hash: str, tip: str
    ) -> None:
        key = game or client_id
        entries = self._load(key)
        now = datetime.now().isoformat(timespec="seconds")

        entry = {
            "timestamp": now,
            "image_hash": image_hash,
            "tip": tip,
            "client_id": client_id,
        }

        entries.append(entry)

        # Trim to max entries in memory
        if len(entries) > self._max_entries:
            entries[:] = entries[-self._max_entries:]

        # Append to file
        self._ensure_dir()
        path = self._file_path(key)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as err:
            _LOGGER.error("Failed to append history %s: %s", path, err)

    async def get_recent(self, key: str, count: int = 5) -> list[dict]:
        entries = self._load(key)
        return entries[-count:]

    async def is_duplicate_image(self, image_hash: str, key: str | None = None) -> bool:
        """Check if the same image was processed within the dedup window."""
        now = time.time()
        keys = [key] if key else list(self._cache.keys())

        for k in keys:
            entries = self._load(k)
            for entry in reversed(entries):
                if entry.get("image_hash") == image_hash:
                    try:
                        entry_time = datetime.fromisoformat(entry["timestamp"]).timestamp()
                        if now - entry_time < IMAGE_DEDUP_WINDOW_SECONDS:
                            return True
                    except (ValueError, OSError):
                        pass
                    break  # Only check most recent match per key
        return False

    async def cleanup(self, max_age_days: int | None = None) -> int:
        """Remove entries older than max_age_days. Returns number of removed entries."""
        max_age = max_age_days if max_age_days is not None else self._max_age_days
        cutoff = time.time() - max_age * 86400
        total_removed = 0

        self._ensure_dir()
        for path in self._base_path.glob("*.jsonl"):
            entries: list[dict] = []
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        try:
                            entry_time = datetime.fromisoformat(
                                entry["timestamp"]
                            ).timestamp()
                            if entry_time >= cutoff:
                                entries.append(entry)
                            else:
                                total_removed += 1
                        except (ValueError, KeyError):
                            entries.append(entry)  # Keep entries without valid timestamp
            except OSError as err:
                _LOGGER.warning("Failed to read %s for cleanup: %s", path, err)
                continue

            # Rewrite file with remaining entries
            try:
                with open(path, "w", encoding="utf-8") as f:
                    for entry in entries:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError as err:
                _LOGGER.error("Failed to rewrite %s during cleanup: %s", path, err)

            # Update cache
            key = path.stem
            self._cache[key] = entries

        return total_removed

    async def clear(self, key: str | None = None) -> None:
        if key:
            self._cache.pop(key, None)
            path = self._file_path(key)
            if path.exists():
                path.unlink()
        else:
            self._cache.clear()
            if self._base_path.exists():
                for f in self._base_path.glob("*.jsonl"):
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
