"""Game-specific prompt pack loader."""
from __future__ import annotations

import json
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

_PACKS_DIR = Path(__file__).parent


class PromptPackLoader:
    """Loads and caches prompt packs from JSON files."""

    def __init__(self) -> None:
        self._packs: dict[str, dict] = {}
        self._loaded = False

    def load_all(self) -> dict[str, dict]:
        """Load all prompt pack JSON files from the prompt_packs directory."""
        if self._loaded:
            return self._packs

        for path in _PACKS_DIR.glob("*.json"):
            if path.name.startswith("_"):
                continue  # Skip templates
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                pack_id = data.get("id", path.stem)
                self._packs[pack_id] = data
                _LOGGER.debug("Loaded prompt pack: %s", pack_id)
            except (json.JSONDecodeError, OSError) as err:
                _LOGGER.warning("Failed to load prompt pack %s: %s", path.name, err)

        self._loaded = True
        _LOGGER.info("Loaded %d prompt packs", len(self._packs))
        return self._packs

    def find_by_keyword(self, text: str) -> dict | None:
        """Match a window title or app name against pack keywords.

        Case-insensitive partial match. First match wins.
        """
        if not self._loaded:
            self.load_all()

        text_lower = text.lower()
        for pack in self._packs.values():
            for keyword in pack.get("keywords", []):
                if keyword.lower() in text_lower:
                    return pack
        return None

    def get(self, pack_id: str) -> dict | None:
        if not self._loaded:
            self.load_all()
        return self._packs.get(pack_id)
