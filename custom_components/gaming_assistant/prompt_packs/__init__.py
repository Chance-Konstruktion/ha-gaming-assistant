"""Game-specific prompt pack loader with auto-download support."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import hashlib
import re
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiohttp

_LOGGER = logging.getLogger(__name__)

_BUNDLED_DIR = Path(__file__).parent
_MANIFEST_FILE = _BUNDLED_DIR / "pack_manifest.json"

# Git ref the packs are fetched from. A branch, tag, or commit SHA — pin to a
# release tag (e.g. "v2026.06") for reproducible, auditable updates instead of
# tracking a moving branch.
PROMPTS_REPO_REF = "main"
PROMPTS_REPO_URL = (
    "https://github.com/Chance-Konstruktion/"
    f"ha-gaming-assistant-prompts/archive/{PROMPTS_REPO_REF}.zip"
)

# Repo-root manifest mapping each downloadable pack to its SHA-256, used to
# verify downloads before they are written to the cache.
_REMOTE_MANIFEST_NAME = "checksums.json"

_SPOILER_LEVELS = {"none", "low", "medium", "high"}
_ASSISTANT_MODES = {"coach", "coplay", "opponent", "analyst"}
_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+(?:\.\d+)?$")


def validate_pack(data: dict) -> list[str]:
    """Validate a prompt pack dict against the bundled manifest schema.

    Returns human-readable errors. Required-field defects make the pack
    unusable; optional-field defects remain advisory in the loader.
    """
    if not isinstance(data, dict):
        return ["pack must be a JSON object"]

    errors: list[str] = []
    required = ("id", "name", "keywords", "system_prompt")
    for field in required:
        if field not in data:
            errors.append(f"missing required field '{field}'")

    if "id" in data:
        pack_id = data["id"]
        if not isinstance(pack_id, str):
            errors.append("'id' must be a string")
        elif not _ID_PATTERN.fullmatch(pack_id):
            errors.append(f"'id' must match {_ID_PATTERN.pattern}, got '{pack_id}'")

    for field in ("name", "system_prompt"):
        if field in data:
            value = data[field]
            if not isinstance(value, str) or not value.strip():
                errors.append(f"'{field}' must be a non-empty string")

    if "version" in data:
        version = data["version"]
        if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
            errors.append(
                f"'version' must look like '1.0' or '1.2.3', got {version!r}"
            )

    if "keywords" in data:
        keywords = data["keywords"]
        if not isinstance(keywords, list) or not keywords:
            errors.append("'keywords' must be a non-empty array of strings")
        elif any(not isinstance(k, str) or not k.strip() for k in keywords):
            errors.append("all entries of 'keywords' must be non-empty strings")

    if "spoiler_defaults" in data:
        spoiler_defaults = data["spoiler_defaults"]
        if not isinstance(spoiler_defaults, dict):
            errors.append("'spoiler_defaults' must be an object")
        else:
            for cat, level in spoiler_defaults.items():
                if not isinstance(level, str) or level not in _SPOILER_LEVELS:
                    errors.append(
                        f"'spoiler_defaults.{cat}' must be one of {sorted(_SPOILER_LEVELS)}, "
                        f"got {level!r}"
                    )

    if "constraints" in data:
        constraints = data["constraints"]
        if not isinstance(constraints, dict):
            errors.append("'constraints' must be an object")
        else:
            if "supported_modes" in constraints:
                modes = constraints["supported_modes"]
                if not isinstance(modes, list) or any(
                    not isinstance(mode, str) or mode not in _ASSISTANT_MODES
                    for mode in modes
                ):
                    errors.append(
                        "'constraints.supported_modes' entries must be one of "
                        f"{sorted(_ASSISTANT_MODES)}"
                    )
            if "min_model_params_b" in constraints:
                min_params = constraints["min_model_params_b"]
                if (
                    isinstance(min_params, bool)
                    or not isinstance(min_params, (int, float))
                    or min_params < 0
                ):
                    errors.append("'constraints.min_model_params_b' must be a non-negative number")

    if "examples" in data:
        examples = data["examples"]
        if not isinstance(examples, list):
            errors.append("'examples' must be an array")
        else:
            for i, example in enumerate(examples):
                if (
                    not isinstance(example, dict)
                    or not isinstance(example.get("situation"), str)
                    or not example["situation"].strip()
                    or not isinstance(example.get("tip"), str)
                    or not example["tip"].strip()
                ):
                    errors.append(
                        f"'examples[{i}]' must be an object with non-empty string 'situation' and 'tip'"
                    )

    return errors


def required_field_errors(data: dict) -> list[str]:
    """Return validation errors that make a pack unusable.

    Optional-field issues remain advisory so one malformed optional field
    does not silently remove an otherwise usable pack from the library.
    """
    if not isinstance(data, dict):
        return ["pack must be a JSON object"]

    errors: list[str] = []
    for field in ("id", "name", "keywords", "system_prompt"):
        if field not in data:
            errors.append(f"missing required field '{field}'")

    if "id" in data:
        pack_id = data["id"]
        if not isinstance(pack_id, str):
            errors.append("'id' must be a string")
        elif not _ID_PATTERN.fullmatch(pack_id):
            errors.append(f"'id' must match {_ID_PATTERN.pattern}, got '{pack_id}'")

    for field in ("name", "system_prompt"):
        if field in data:
            value = data[field]
            if not isinstance(value, str) or not value.strip():
                errors.append(f"'{field}' must be a non-empty string")

    if "keywords" in data:
        keywords = data["keywords"]
        if not isinstance(keywords, list) or not keywords:
            errors.append("'keywords' must be a non-empty array of strings")
        elif any(not isinstance(k, str) or not k.strip() for k in keywords):
            errors.append("all entries of 'keywords' must be non-empty strings")

    return errors


class PromptPackLoader:
    """Loads and caches prompt packs from JSON files."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._packs: dict[str, dict] = {}
        self._loaded = False
        self._cache_dir = cache_dir
        self._invalid_packs: dict[str, list[str]] = {}
        self._pack_warnings: dict[str, list[str]] = {}
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

    @property
    def pack_warnings(self) -> dict[str, list[str]]:
        """Map of filename -> advisory issues for packs that loaded anyway."""
        return dict(self._pack_warnings)

    def _try_load_pack(self, path: Path) -> dict | None:
        """Parse + validate a single pack file. Returns dict or None."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError) as err:
            # UnicodeDecodeError (a non-UTF-8 pack, e.g. Latin-1) is a ValueError,
            # not an OSError — without it here a single mis-encoded file in the
            # cache would raise straight through load_all() and abort the entire
            # pack load instead of just skipping the bad file.
            _LOGGER.warning("Failed to load prompt pack %s: %s", path.name, err)
            self._invalid_packs[path.name] = [f"parse error: {err}"]
            return None

        errors = validate_pack(data)
        fatal = required_field_errors(data)
        if fatal:
            _LOGGER.warning(
                "Prompt pack %s is invalid (skipped): %s",
                path.name, "; ".join(fatal),
            )
            self._invalid_packs[path.name] = errors or fatal
            return None
        if errors:
            # Optional-field issues only — load the pack but record the advisory.
            _LOGGER.warning(
                "Prompt pack %s loaded with advisory issues: %s",
                path.name, "; ".join(errors),
            )
            self._pack_warnings[path.name] = errors
        return data

    def _load_from_dir(self, directory: Path) -> int:
        """Load all JSON packs from a directory (recursive). Returns count loaded."""
        count = 0
        if not directory.is_dir():
            return count
        for path in directory.rglob("*.json"):
            if path.name.startswith("_") or path.name == "pack_manifest.json":
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
            if path.name.startswith("_") or path.name == "pack_manifest.json":
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
        self._pack_warnings.clear()
        self._loaded = False
        return self.load_all()


def _read_remote_manifest(
    zf: zipfile.ZipFile,
) -> tuple[bool, dict[str, str] | None]:
    """Return (present, hashes) for the archive's checksum manifest.

    A missing manifest is distinct from a present but malformed manifest:
    only the former is eligible for the legacy unverified-download fallback.
    """
    for info in zf.infolist():
        if info.is_dir():
            continue
        parts = info.filename.split("/")
        # The manifest sits at the repo root: "<repo-folder>/checksums.json".
        if len(parts) == 2 and parts[1] == _REMOTE_MANIFEST_NAME:
            try:
                data = json.loads(zf.read(info.filename))
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                return True, None
            if not isinstance(data, dict) or data.get("algorithm") != "sha256":
                return True, None
            packs = data.get("packs")
            if not isinstance(packs, dict) or not packs:
                return True, None
            if any(
                not isinstance(path, str)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                for path, digest in packs.items()
            ):
                return True, None
            return True, packs
    return False, None


def extract_prompt_packs(zip_bytes: bytes, cache_dir: Path) -> int:
    """Extract and checksum-verify packs from a downloaded repo zip.

    When the repo ships a ``checksums.json`` manifest, every pack is verified
    against its SHA-256 before being written: packs missing from the manifest or
    whose hash does not match are skipped (so a tampered or corrupted download
    cannot replace a good pack). If no manifest is present (older prompts repo),
    packs are written unverified with a warning. Returns the number of packs
    written to the cache.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    rejected = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        manifest_present, manifest = _read_remote_manifest(zf)
        if manifest_present and manifest is None:
            _LOGGER.error(
                "Rejecting prompt pack archive: invalid %s", _REMOTE_MANIFEST_NAME
            )
            return 0
        if manifest is None:
            _LOGGER.warning(
                "No %s in download — writing packs unverified", _REMOTE_MANIFEST_NAME
            )
        for info in zf.infolist():
            if info.is_dir() or not info.filename.endswith(".json"):
                continue
            # Files are in: ha-gaming-assistant-prompts-<ref>/packs/...
            parts = info.filename.split("/")
            try:
                packs_idx = parts.index("packs")
            except ValueError:
                continue
            # Relative path after packs/, e.g. "base/elden_ring.json"
            rel_parts = parts[packs_idx + 1:]
            if (
                not rel_parts
                or rel_parts[-1].startswith("_")
                or any(part in {"", ".", ".."} for part in rel_parts)
                or any("\\" in part for part in rel_parts)
            ):
                _LOGGER.warning("Skipping unsafe prompt pack path in archive: %s", info.filename)
                rejected += 1
                continue
            rel_path = Path(*rel_parts)
            if rel_path.is_absolute():
                _LOGGER.warning("Skipping absolute prompt pack path in archive: %s", info.filename)
                rejected += 1
                continue
            rel_key = rel_path.as_posix()
            raw = zf.read(info.filename)

            if manifest is not None:
                expected = manifest.get(rel_key)
                if expected is None:
                    _LOGGER.warning("Skipping %s: not in %s", rel_key, _REMOTE_MANIFEST_NAME)
                    rejected += 1
                    continue
                actual = hashlib.sha256(raw).hexdigest()
                if actual != expected:
                    _LOGGER.warning(
                        "Skipping %s: checksum mismatch (expected %s…, got %s…)",
                        rel_key, expected[:12], actual[:12],
                    )
                    rejected += 1
                    continue

            target = cache_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            count += 1

    if rejected:
        _LOGGER.warning(
            "Rejected %d unverified/altered pack(s) during download", rejected
        )
    _LOGGER.info("Extracted %d prompt packs to %s", count, cache_dir)
    return count


async def download_prompt_packs(
    cache_dir: Path,
    async_add_executor_job: Callable[..., Awaitable[int]] | None = None,
) -> bool:
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

        # ZIP parsing, hashing, decompression and writes are synchronous CPU/I/O.
        # Use Home Assistant's executor when available; keep standalone callers
        # non-blocking as well.
        if async_add_executor_job is None:
            extracted = await asyncio.to_thread(extract_prompt_packs, data, cache_dir)
        else:
            extracted = await async_add_executor_job(
                extract_prompt_packs, data, cache_dir
            )
        return extracted > 0

    except (aiohttp.ClientError, zipfile.BadZipFile, OSError) as err:
        _LOGGER.error("Failed to download prompt packs: %s", err)
        return False
