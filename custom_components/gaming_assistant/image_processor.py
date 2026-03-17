"""Central image processing pipeline for Gaming Assistant."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging

import requests

from .const import (
    HISTORY_CONTEXT_SIZE,
    OLLAMA_NUM_PREDICT,
    OLLAMA_RETRY_DELAY,
    OLLAMA_TIMEOUT,
)
from .game_state import GameStateManager, extract_observations_from_tip
from .history import HistoryManager
from .prompt_builder import PromptBuilder
from .spoiler import SpoilerManager

_LOGGER = logging.getLogger(__name__)


class ImageProcessor:
    """Central image processing pipeline.

    Pipeline:
    1. Receive image (JPEG bytes)
    2. Compute hash
    3. Check deduplication (via HistoryManager)
    4. Game detection (via metadata)
    5. Load spoiler settings
    6. Load history
    7. Build prompt
    8. Ollama call (image + prompt)
    9. Parse response
    10. Store in history
    11. Return tip
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
        if self._compact:
            _LOGGER.info(
                "Small model detected (%s) — using compact prompts", model
            )

    @property
    def timeout(self) -> int:
        return self._timeout

    @timeout.setter
    def timeout(self, value: int) -> None:
        self._timeout = value

    async def process(
        self,
        image_bytes: bytes,
        client_id: str,
        metadata: dict | None = None,
    ) -> str:
        """Run the full image processing pipeline. Returns the tip string."""
        metadata = metadata or {}

        # 1. Compute hash
        image_hash = hashlib.md5(image_bytes).hexdigest()

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

        # 5. Load spoiler settings
        spoiler_settings = self._spoiler.get_settings(game or None)
        spoiler_block = SpoilerManager.generate_prompt_block(spoiler_settings)

        # 6. Load history
        recent = await self._history.get_recent(key, HISTORY_CONTEXT_SIZE)
        history_context = HistoryManager.format_for_prompt(recent)

        # 6b. Game state context
        state_context = ""
        if self._game_state and game:
            state_context = self._game_state.format_for_prompt(
                game, compact=self._compact
            )

        # 7. Build prompt
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

        # 8. Call Ollama
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        tip = await self._call_ollama(prompt, image_b64)

        if not tip:
            return ""

        # 9. Store in history
        await self._history.add_entry(game, client_id, image_hash, tip)

        # 10. Extract and store game state observations
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
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            answer = await self._call_ollama(prompt, image_b64)
            image_hash = hashlib.md5(image_bytes).hexdigest()
        else:
            answer = await self._call_ollama_text(prompt)
            image_hash = None

        if answer and image_hash:
            await self._history.add_entry(game, client_id, image_hash, answer)

        return answer

    @staticmethod
    def _clean_response(text: str) -> str:
        """Strip incomplete trailing sentences caused by num_predict cutoff."""
        if not text:
            return text
        # If the text ends with proper punctuation, it's complete
        if text[-1] in ".!?)\"'":
            return text
        # Find the last sentence-ending punctuation
        for i in range(len(text) - 1, -1, -1):
            if text[i] in ".!?)":
                return text[:i + 1]
        # No sentence end found -- return as-is (better than nothing)
        return text

    async def _call_ollama(self, prompt: str, image_b64: str) -> str:
        """Send image + prompt to Ollama and return the response."""
        url = f"{self._ollama_host}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": {
                "temperature": 0.4,
                "num_predict": OLLAMA_NUM_PREDICT,
            },
        }

        loop = asyncio.get_event_loop()

        for attempt in range(2):  # 1 retry
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.post(url, json=payload, timeout=self._timeout),
                )
                response.raise_for_status()
                raw = response.json().get("response", "").strip()
                return self._clean_response(raw)
            except requests.exceptions.Timeout:
                _LOGGER.warning(
                    "Ollama timeout (attempt %d/2), retrying in %ds",
                    attempt + 1, OLLAMA_RETRY_DELAY,
                )
                if attempt == 0:
                    await asyncio.sleep(OLLAMA_RETRY_DELAY)
            except requests.exceptions.ConnectionError:
                _LOGGER.error("Cannot reach Ollama at %s", self._ollama_host)
                return ""
            except Exception as err:
                _LOGGER.exception("Ollama call failed: %s", err)
                return ""

        _LOGGER.error("Ollama request failed after retries")
        return ""

    async def _call_ollama_text(self, prompt: str) -> str:
        """Send text-only prompt to Ollama and return the response."""
        url = f"{self._ollama_host}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.4,
                "num_predict": OLLAMA_NUM_PREDICT,
            },
        }

        loop = asyncio.get_event_loop()

        for attempt in range(2):
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.post(url, json=payload, timeout=self._timeout),
                )
                response.raise_for_status()
                return response.json().get("response", "").strip()
            except requests.exceptions.Timeout:
                _LOGGER.warning(
                    "Ollama text timeout (attempt %d/2), retrying in %ds",
                    attempt + 1, OLLAMA_RETRY_DELAY,
                )
                if attempt == 0:
                    await asyncio.sleep(OLLAMA_RETRY_DELAY)
            except requests.exceptions.ConnectionError:
                _LOGGER.error("Cannot reach Ollama at %s", self._ollama_host)
                return ""
            except Exception as err:
                _LOGGER.exception("Ollama text call failed: %s", err)
                return ""

        _LOGGER.error("Ollama text request failed after retries")
        return ""
