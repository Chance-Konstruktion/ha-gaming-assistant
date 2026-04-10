"""Game-specific prompt pack loader with auto-download support."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import zipfile
from pathlib import Path

import aiohttp

_LOGGER = logging.getLogger(__name__)

_BUNDLED_DIR = Path(__file__).parent

PROMPTS_REPO_URL = (
    "https://github.com/Chance-Konstruktion/"
    "ha-gaming-assistant-prompts/archive/refs/heads/main.zip"
)


class PromptPackLoader:
    """Loads and caches prompt packs from JSON files."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._packs: dict[str, dict] = {}
        self._loaded = False
        self._cache_dir = cache_dir

    def _load_from_dir(self, directory: Path) -> int:
        """Load all JSON packs from a directory. Returns count loaded."""
        count = 0
        if not directory.is_dir():
            return count
        for path in directory.glob("*.json"):
            if path.name.startswith("_"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                pack_id = data.get("id", path.stem)
                self._packs[pack_id] = data
                count += 1
            except (json.JSONDecodeError, OSError) as err:
                _LOGGER.warning("Failed to load prompt pack %s: %s", path.name, err)
        return count

    def load_all(self) -> dict[str, dict]:
        """Load all prompt pack JSON files.

        Loads from cache first (downloaded packs), then fills in any
        missing packs from the bundled directory.
        """
        if self._loaded:
            return self._packs

        # 1. Load from downloaded cache (takes priority)
        if self._cache_dir:
            cached = self._load_from_dir(self._cache_dir)
            _LOGGER.debug("Loaded %d packs from cache", cached)

        # 2. Fill in from bundled packs (fallback)
        bundled_count = 0
        for path in _BUNDLED_DIR.glob("*.json"):
            if path.name.startswith("_"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                pack_id = data.get("id", path.stem)
                if pack_id not in self._packs:
                    self._packs[pack_id] = data
                    bundled_count += 1
            except (json.JSONDecodeError, OSError) as err:
                _LOGGER.warning("Failed to load prompt pack %s: %s", path.name, err)

        self._loaded = True
        _LOGGER.info(
            "Loaded %d prompt packs total (%d cached, %d bundled)",
            len(self._packs),
            len(self._packs) - bundled_count,
            bundled_count,
        )
        return self._packs

    def find_by_keyword(self, text: str) -> dict | None:
        """Match a window title or app name against pack keywords."""
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

    def reload(self) -> dict[str, dict]:
        """Force reload all packs (e.g. after downloading new ones)."""
        self._packs.clear()
        self._loaded = False
        return self.load_all()


async def download_prompt_packs(cache_dir: Path) -> bool:
    """Download latest prompt packs from GitHub to cache directory.

    Returns True on success, False on failure.
    """
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            _LOGGER.info("Downloading prompt packs from %s", PROMPTS_REPO_URL)
            async with session.get(PROMPTS_REPO_URL) as resp:
                if resp.status != 200:
                    _LOGGER.error(
                        "Failed to download prompt packs: HTTP %s", resp.status
                    )
                    return False
                data = await resp.read()

        # Extract JSON files from the packs/ directory in the zip
        zip_buf = io.BytesIO(data)
        count = 0
        with zipfile.ZipFile(zip_buf) as zf:
            for info in zf.infolist():
                # Files are in: ha-gaming-assistant-prompts-main/packs/*.json
                parts = info.filename.split("/")
                if (
                    len(parts) >= 3
                    and parts[1] == "packs"
                    and parts[-1].endswith(".json")
                    and not info.is_dir()
                ):
                    filename = parts[-1]
                    content = zf.read(info.filename)
                    target = cache_dir / filename
                    target.write_bytes(content)
                    count += 1

        _LOGGER.info("Downloaded %d prompt packs to %s", count, cache_dir)
        return count > 0

    except (aiohttp.ClientError, zipfile.BadZipFile, OSError) as err:
        _LOGGER.error("Failed to download prompt packs: %s", err)
        return False
