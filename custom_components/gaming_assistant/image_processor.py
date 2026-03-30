"""Central image processing pipeline for Gaming Assistant."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import time

from .const import (
    HISTORY_CONTEXT_SIZE,
    IMAGE_DOWNSCALE_QUALITY,
    IMAGE_MAX_DIMENSION,
    OLLAMA_NUM_PREDICT,
    OLLAMA_TIMEOUT,
)
from .game_state import GameStateManager, extract_observations_from_tip
from .history import HistoryManager
from .llm_backend import LLMBackend, OllamaBackend, create_backend
from .prompt_builder import PromptBuilder
from .spoiler import SpoilerManager

_LOGGER = logging.getLogger(__name__)

# LLM response cache: reuse tip when game state changed < 5%
_CACHE_SIMILARITY_THRESHOLD = 0.05  # 5% change threshold
_CACHE_MAX_AGE = 120  # seconds


class _CachedResponse:
    """Cached LLM response with metadata for similarity-based reuse."""

    __slots__ = ("tip", "image_phash", "state_keys", "timestamp")

    def __init__(self, tip: str, image_phash: int, state_keys: frozenset[tuple[str, str]]) -> None:
        self.tip = tip
        self.image_phash = image_phash
        self.state_keys = state_keys
        self.timestamp = time.monotonic()

    @property
    def age(self) -> float:
        return time.monotonic() - self.timestamp


class ImageProcessor:
    """Central image processing pipeline.

    Pipeline:
    1. Receive image (JPEG bytes)
    2. Compute perceptual hash (pHash) + content hash
    3. Check deduplication (via HistoryManager)
    4. Game detection (via metadata)
    5. Check LLM cache (state similarity)
    6. Load spoiler settings
    7. Load history
    8. Build prompt (with state context)
    9. Downscale + compress image (WebP when supported)
    10. LLM call (image + prompt) via pluggable backend
    11. Store in history + cache
    12. Extract game state observations
    13. Return tip
    """

    def __init__(
        self,
        ollama_host: str,
        model: str,
        history_manager: HistoryManager,
        spoiler_manager: SpoilerManager,
        prompt_pack_loader=None,
        timeout: int | None = None,
        language: str = "",
        game_state_manager: GameStateManager | None = None,
        llm_backend: LLMBackend | None = None,
    ) -> None:
        self._ollama_host = ollama_host.rstrip("/")
        self._model = model
        self._history = history_manager
        self._spoiler = spoiler_manager
        self._pack_loader = prompt_pack_loader
        self._timeout = timeout or OLLAMA_TIMEOUT
        self._language = language
        self._game_state = game_state_manager
        self._compact = PromptBuilder.is_small_model(model)

        # LLM backend: use provided backend or create default Ollama backend
        if llm_backend:
            self._backend = llm_backend
        else:
            self._backend = OllamaBackend(
                host=self._ollama_host,
                model=self._model,
                timeout=self._timeout,
            )

        # Per-game LLM response cache
        self._cache: dict[str, _CachedResponse] = {}

        if self._compact:
            _LOGGER.info(
                "Small model detected (%s) — using compact prompts", model
            )

    @staticmethod
    def _compute_phash(image_bytes: bytes) -> int:
        """Compute a perceptual hash (pHash) of the image.

        Uses average hash as a fast approximation of pHash.
        Falls back to MD5-based int if Pillow is unavailable.
        """
        try:
            from PIL import Image
        except ImportError:
            return int(hashlib.md5(image_bytes).hexdigest()[:16], 16)

        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("L")
            img = img.resize((8, 8), Image.LANCZOS)
            pixels = list(img.getdata())
            avg = sum(pixels) / len(pixels)
            bits = 0
            for px in pixels:
                bits = (bits << 1) | (1 if px >= avg else 0)
            return bits
        except Exception:
            return int(hashlib.md5(image_bytes).hexdigest()[:16], 16)

    @staticmethod
    def _hamming_distance(h1: int, h2: int) -> int:
        """Count differing bits between two hashes."""
        return bin(h1 ^ h2).count("1")

    @staticmethod
    def _downscale_image(image_bytes: bytes) -> bytes:
        """Downscale and compress image for LLM.

        Uses WebP format when Pillow supports it (smaller than JPEG at same quality),
        falling back to JPEG otherwise.
        """
        try:
            from PIL import Image
        except ImportError:
            return image_bytes

        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            return image_bytes  # Not a valid image — let LLM deal with it

        w, h = img.size
        needs_resize = w > IMAGE_MAX_DIMENSION or h > IMAGE_MAX_DIMENSION

        if not needs_resize and len(image_bytes) < 500_000:
            return image_bytes

        if needs_resize:
            scale = IMAGE_MAX_DIMENSION / max(w, h)
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)
        else:
            new_w, new_h = w, h

        # Try WebP first (better compression), fall back to JPEG
        buf = io.BytesIO()
        try:
            img.save(buf, format="WEBP", quality=IMAGE_DOWNSCALE_QUALITY)
            fmt = "WebP"
        except Exception:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=IMAGE_DOWNSCALE_QUALITY)
            fmt = "JPEG"

        result = buf.getvalue()
        _LOGGER.debug(
            "Image optimized (%s): %dx%d → %dx%d (%d → %d bytes)",
            fmt, w, h, new_w, new_h, len(image_bytes), len(result),
        )
        return result

    def _check_cache(self, game: str, phash: int) -> str | None:
        """Check if a cached response is still valid for this game state.

        Returns the cached tip if the game state changed less than the
        similarity threshold, or None if a fresh LLM call is needed.
        """
        cached = self._cache.get(game)
        if cached is None:
            return None

        # Expire old cache entries
        if cached.age > _CACHE_MAX_AGE:
            del self._cache[game]
            return None

        # Check perceptual image similarity (hamming distance < 5 = very similar)
        if self._hamming_distance(cached.image_phash, phash) > 5:
            return None

        # Check game state similarity
        if self._game_state and game:
            current = self._game_state.get_current(game) or {}
            current_keys = frozenset(
                (str(k), str(v)) for k, v in current.items()
            )
            if cached.state_keys:
                total = max(len(current_keys | cached.state_keys), 1)
                changed = len(current_keys ^ cached.state_keys)
                if changed / total > _CACHE_SIMILARITY_THRESHOLD:
                    return None

        _LOGGER.debug("LLM cache hit for %s (age=%.0fs)", game, cached.age)
        return cached.tip

    def _update_cache(self, game: str, tip: str, phash: int) -> None:
        """Store a response in the cache."""
        state_keys: frozenset[tuple[str, str]] = frozenset()
        if self._game_state and game:
            current = self._game_state.get_current(game) or {}
            state_keys = frozenset(
                (str(k), str(v)) for k, v in current.items()
            )
        self._cache[game] = _CachedResponse(tip, phash, state_keys)

    @property
    def timeout(self) -> int:
        return self._timeout

    @timeout.setter
    def timeout(self, value: int) -> None:
        self._timeout = value
        self._backend.timeout = value

    @property
    def backend(self) -> LLMBackend:
        """Return the current LLM backend."""
        return self._backend

    @backend.setter
    def backend(self, value: LLMBackend) -> None:
        """Swap the LLM backend at runtime."""
        self._backend = value
        self._cache.clear()  # Invalidate cache when backend changes
        _LOGGER.info("LLM backend changed to: %s (%s)", value.backend_type, value.model)

    async def process(
        self,
        image_bytes: bytes,
        client_id: str,
        metadata: dict | None = None,
    ) -> str:
        """Run the full image processing pipeline. Returns the tip string."""
        metadata = metadata or {}

        # 1. Compute hashes
        image_hash = hashlib.md5(image_bytes).hexdigest()
        image_phash = self._compute_phash(image_bytes)

        # 2. Extract game info from metadata
        game = metadata.get("window_title", "") or metadata.get("game", "")
        client_type = metadata.get("client_type", "pc")
        assistant_mode = metadata.get("assistant_mode", "coach")

        # 3. Deduplication check
        key = game or client_id
        if await self._history.is_duplicate_image(image_hash, key):
            _LOGGER.debug("Duplicate image %s, skipping analysis", image_hash[:8])
            return ""

        # 4. Find prompt pack by game keyword
        prompt_pack = None
        if self._pack_loader and game:
            prompt_pack = self._pack_loader.find_by_keyword(game)
            if prompt_pack:
                _LOGGER.debug("Using prompt pack: %s", prompt_pack.get("name"))
                if prompt_pack.get("spoiler_defaults"):
                    self._spoiler.apply_pack_defaults(game, prompt_pack["spoiler_defaults"])

        # 5. Check LLM cache (game state similarity)
        cached_tip = self._check_cache(game, image_phash)
        if cached_tip:
            return cached_tip

        # 6. Load spoiler settings
        spoiler_settings = self._spoiler.get_settings(game or None)
        spoiler_block = SpoilerManager.generate_prompt_block(spoiler_settings)

        # 7. Load history
        recent = await self._history.get_recent(key, HISTORY_CONTEXT_SIZE)
        history_context = HistoryManager.format_for_prompt(recent)

        # 7b. Game state context
        state_context = ""
        if self._game_state and game:
            state_context = self._game_state.format_for_prompt(
                game, compact=self._compact
            )

        # 8. Build prompt
        prompt = PromptBuilder.build(
            game=game,
            spoiler_block=spoiler_block,
            history_context=history_context,
            prompt_pack=prompt_pack,
            client_type=client_type,
            assistant_mode=assistant_mode,
            language=self._language,
            compact=self._compact,
            state_context=state_context,
        )

        # 9. Downscale + compress image
        llm_image = self._downscale_image(image_bytes)

        # 10. Call LLM backend
        image_b64 = base64.b64encode(llm_image).decode("utf-8")
        response = await self._backend.generate(
            prompt, image_b64, max_tokens=OLLAMA_NUM_PREDICT
        )
        tip = response.text

        if not tip:
            return ""

        # 11. Store in history + cache
        await self._history.add_entry(game, client_id, image_hash, tip)
        self._update_cache(game, tip, image_phash)

        # 12. Extract and store game state observations
        if self._game_state and game:
            observations = extract_observations_from_tip(
                tip, game, prompt_pack
            )
            if observations:
                self._game_state.update(
                    game, observations, tip=tip, source=client_id
                )

        return tip

    async def ask(
        self,
        question: str,
        client_id: str = "ask",
        metadata: dict | None = None,
        image_bytes: bytes | None = None,
    ) -> str:
        """Answer a direct user question (optional image context)."""
        metadata = metadata or {}

        game = metadata.get("window_title", "") or metadata.get("game", "")
        client_type = metadata.get("client_type", "pc")
        assistant_mode = metadata.get("assistant_mode", "coach")

        prompt_pack = None
        if self._pack_loader and game:
            prompt_pack = self._pack_loader.find_by_keyword(game)

        spoiler_settings = self._spoiler.get_settings(game or None)
        spoiler_block = SpoilerManager.generate_prompt_block(spoiler_settings)

        key = game or client_id
        recent = await self._history.get_recent(key, HISTORY_CONTEXT_SIZE)
        history_context = HistoryManager.format_for_prompt(recent)

        state_context = ""
        if self._game_state and game:
            state_context = self._game_state.format_for_prompt(
                game, compact=self._compact
            )

        prompt = PromptBuilder.build(
            game=game,
            spoiler_block=spoiler_block,
            history_context=history_context,
            prompt_pack=prompt_pack,
            client_type=client_type,
            user_question=question,
            assistant_mode=assistant_mode,
            language=self._language,
            compact=self._compact,
            state_context=state_context,
        )

        if image_bytes:
            llm_image = self._downscale_image(image_bytes)
            image_b64 = base64.b64encode(llm_image).decode("utf-8")
            response = await self._backend.generate(
                prompt, image_b64, max_tokens=OLLAMA_NUM_PREDICT
            )
            answer = response.text
            image_hash = hashlib.md5(image_bytes).hexdigest()
        else:
            response = await self._backend.generate_text(
                prompt, max_tokens=OLLAMA_NUM_PREDICT
            )
            answer = response.text
            image_hash = None

        if answer and image_hash:
            await self._history.add_entry(game, client_id, image_hash, answer)

        return answer

    # -- backward compatibility aliases --------------------------------------

    async def _call_ollama(self, prompt: str, image_b64: str) -> str:
        """Legacy method — delegates to backend.generate()."""
        response = await self._backend.generate(
            prompt, image_b64, max_tokens=OLLAMA_NUM_PREDICT
        )
        return response.text

    async def _call_ollama_text(self, prompt: str) -> str:
        """Legacy method — delegates to backend.generate_text()."""
        response = await self._backend.generate_text(
            prompt, max_tokens=OLLAMA_NUM_PREDICT
        )
        return response.text
