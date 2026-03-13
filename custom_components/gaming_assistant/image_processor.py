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
    ) -> None:
        self._ollama_host = ollama_host.rstrip("/")
        self._model = model
        self._history = history_manager
        self._spoiler = spoiler_manager
        self._pack_loader = prompt_pack_loader

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

        # 7. Build prompt
        prompt = PromptBuilder.build(
            game=game,
            spoiler_block=spoiler_block,
            history_context=history_context,
            prompt_pack=prompt_pack,
            client_type=client_type,
        )

        # 8. Call Ollama
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        tip = await self._call_ollama(prompt, image_b64)

        if not tip:
            return ""

        # 9. Store in history
        await self._history.add_entry(game, client_id, image_hash, tip)

        return tip

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
                    lambda: requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT),
                )
                response.raise_for_status()
                return response.json().get("response", "").strip()
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
