"""Game-specific prompt pack loader with auto-download support."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import zipfile
from pathlib import Path

import aiohttp

_LOGGER = logging.getLogger(__name__)

_BUNDLED_DIR = Path(__file__).parent
_MANIFEST_FILE = _BUNDLED_DIR / "manifest.json"

PROMPTS_REPO_URL = (
    "https://github.com/Chance-Konstruktion/"
    "ha-gaming-assistant-prompts/archive/refs/heads/main.zip"
)

_SPOILER_LEVELS = {"none", "low", "medium", "high"}
_ASSISTANT_MODES = {"coach", "coplay", "opponent", "analyst"}
_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+(?:\.\d+)?$")


def validate_pack(data: dict) -> list[str]:
    """Validate a prompt pack dict against the manifest schema.

    Returns a list of human-readable error strings. An empty list means
    the pack is valid. The validation is deliberately lightweight – it
    mirrors the bundled manifest.json without pulling in jsonschema.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["pack must be a JSON object"]

    # Required fields
    for field in ("id", "name", "keywords", "system_prompt"):
        if field not in data:
            errors.append(f"missing required field '{field}'")

    pack_id = data.get("id")
    if isinstance(pack_id, str) and not _ID_PATTERN.match(pack_id):
        errors.append(f"'id' must match {_ID_PATTERN.pattern}, got '{pack_id}'")

    if "version" in data:
        version = data["version"]
        if not isinstance(version, str) or not _VERSION_PATTERN.match(version):
            errors.append(
                f"'version' must look like '1.0' or '1.2.3', got {version!r}"
            )

    keywords = data.get("keywords")
    if keywords is not None:
        if not isinstance(keywords, list) or not keywords:
            errors.append("'keywords' must be a non-empty array of strings")
        elif any(not isinstance(k, str) or not k for k in keywords):
            errors.append("all entries of 'keywords' must be non-empty strings")

    spoiler_defaults = data.get("spoiler_defaults")
    if spoiler_defaults is not None:
        if not isinstance(spoiler_defaults, dict):
            errors.append("'spoiler_defaults' must be an object")
        else:
            for cat, level in spoiler_defaults.items():
                if level not in _SPOILER_LEVELS:
                    errors.append(
                        f"'spoiler_defaults.{cat}' must be one of {sorted(_SPOILER_LEVELS)}, "
                        f"got {level!r}"
                    )

    constraints = data.get("constraints")
    if constraints is not None:
        if not isinstance(constraints, dict):
            errors.append("'constraints' must be an object")
        else:
            modes = constraints.get("supported_modes")
            if modes is not None:
                if not isinstance(modes, list) or any(
                    m not in _ASSISTANT_MODES for m in modes
                ):
                    errors.append(
                        "'constraints.supported_modes' entries must be one of "
                        f"{sorted(_ASSISTANT_MODES)}"
                    )
            min_params = constraints.get("min_model_params_b")
            if min_params is not None and not isinstance(
                min_params, (int, float)
            ):
                errors.append("'constraints.min_model_params_b' must be a number")

    examples = data.get("examples")
    if examples is not None:
        if not isinstance(examples, list):
            errors.append("'examples' must be an array")
        else:
            for i, ex in enumerate(examples):
                if not isinstance(ex, dict) or "situation" not in ex or "tip" not in ex:
                    errors.append(
                        f"'examples[{i}]' must be an object with 'situation' and 'tip'"
                    )

    return errors


class PromptPackLoader:
    """Loads and caches prompt packs from JSON files."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._packs: dict[str, dict] = {}
        self._loaded = False
        self._cache_dir = cache_dir
        self._invalid_packs: dict[str, list[str]] = {}
        self._manifest: dict | None = None

    @property
    def manifest(self) -> dict:
        """Return the bundled manifest metadata (lazy-loaded)."""
        if self._manifest is None:
            try:
                self._manifest = json.loads(
                    _MANIFEST_FILE.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError) as err:
                _LOGGER.warning("Could not load prompt pack manifest: %s", err)
                self._manifest = {}
        return self._manifest

    @property
    def invalid_packs(self) -> dict[str, list[str]]:
        """Map of filename -> list of validation errors for packs that failed."""
        return dict(self._invalid_packs)

    def _try_load_pack(self, path: Path) -> dict | None:
        """Parse + validate a single pack file. Returns dict or None."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as err:
            _LOGGER.warning("Failed to load prompt pack %s: %s", path.name, err)
            self._invalid_packs[path.name] = [f"parse error: {err}"]
            return None

        errors = validate_pack(data)
        if errors:
            _LOGGER.warning(
                "Prompt pack %s is invalid: %s", path.name, "; ".join(errors)
            )
            self._invalid_packs[path.name] = errors
            return None
        return data

    def _load_from_dir(self, directory: Path) -> int:
        """Load all JSON packs from a directory (recursive). Returns count loaded."""
        count = 0
        if not directory.is_dir():
            return count
        for path in directory.rglob("*.json"):
            if path.name.startswith("_") or path.name == "manifest.json":
                continue
            data = self._try_load_pack(path)
            if data is None:
                continue
            pack_id = data.get("id", path.stem)
            self._packs[pack_id] = data
            count += 1
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
        for path in _BUNDLED_DIR.rglob("*.json"):
            if path.name.startswith("_") or path.name == "manifest.json":
                continue
            data = self._try_load_pack(path)
            if data is None:
                continue
            pack_id = data.get("id", path.stem)
            if pack_id not in self._packs:
                self._packs[pack_id] = data
                bundled_count += 1

        self._loaded = True
        _LOGGER.info(
            "Loaded %d prompt packs total (%d cached, %d bundled, %d invalid)",
            len(self._packs),
            len(self._packs) - bundled_count,
            bundled_count,
            len(self._invalid_packs),
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
        self._invalid_packs.clear()
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

        # Extract JSON files from the packs/ directory in the zip,
        # preserving subdirectory structure (base/, cheats/, secrets/, completion/)
        zip_buf = io.BytesIO(data)
        count = 0
        with zipfile.ZipFile(zip_buf) as zf:
            for info in zf.infolist():
                if info.is_dir() or not info.filename.endswith(".json"):
                    continue
                # Files are in: ha-gaming-assistant-prompts-main/packs/...
                parts = info.filename.split("/")
                try:
                    packs_idx = parts.index("packs")
                except ValueError:
                    continue
                # Relative path after packs/, e.g. "base/elden_ring.json"
                rel_parts = parts[packs_idx + 1:]
                if not rel_parts or rel_parts[-1].startswith("_"):
                    continue
                rel_path = Path(*rel_parts)
                target = cache_dir / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info.filename))
                count += 1

        _LOGGER.info("Downloaded %d prompt packs to %s", count, cache_dir)
        return count > 0

    except (aiohttp.ClientError, zipfile.BadZipFile, OSError) as err:
        _LOGGER.error("Failed to download prompt packs: %s", err)
        return False
