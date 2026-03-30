"""Unit tests for ImageProcessor – timeout configuration and backend integration."""

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

# Stub homeassistant before importing our modules
_HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.mqtt",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.event",
]
for mod in _HA_MODULES:
    sys.modules.setdefault(mod, MagicMock())

from custom_components.gaming_assistant.image_processor import ImageProcessor
from custom_components.gaming_assistant.llm_backend import LLMResponse, OllamaBackend
from custom_components.gaming_assistant.history import HistoryManager
from custom_components.gaming_assistant.spoiler import SpoilerManager
from custom_components.gaming_assistant.const import OLLAMA_TIMEOUT


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_aiohttp_response(json_data, status=200):
    """Create a mock aiohttp response context manager."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value=json_data)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


class TestImageProcessorTimeout(unittest.TestCase):
    """Tests for configurable Ollama timeout."""

    def _make_processor(self, timeout=None):
        history = MagicMock(spec=HistoryManager)
        history.is_duplicate_image = AsyncMock(return_value=False)
        history.get_recent = AsyncMock(return_value=[])
        history.add_entry = AsyncMock(return_value=None)

        spoiler = MagicMock(spec=SpoilerManager)
        spoiler.get_settings.return_value = {}
        spoiler.generate_prompt_block.return_value = ""

        return ImageProcessor(
            ollama_host="http://localhost:11434",
            model="test-model",
            history_manager=history,
            spoiler_manager=spoiler,
            timeout=timeout,
        )

    def test_default_timeout(self):
        proc = self._make_processor()
        self.assertEqual(proc._timeout, OLLAMA_TIMEOUT)

    def test_custom_timeout(self):
        proc = self._make_processor(timeout=120)
        self.assertEqual(proc._timeout, 120)

    def test_timeout_propagates_to_backend(self):
        """Verify the configured timeout is propagated to the backend."""
        proc = self._make_processor(timeout=180)
        self.assertEqual(proc.backend.timeout, 180)

    def test_timeout_setter(self):
        proc = self._make_processor()
        proc.timeout = 200
        self.assertEqual(proc._timeout, 200)
        self.assertEqual(proc.backend.timeout, 200)

    def test_min_timeout_boundary(self):
        proc = self._make_processor(timeout=10)
        self.assertEqual(proc._timeout, 10)

    def test_max_timeout_boundary(self):
        proc = self._make_processor(timeout=300)
        self.assertEqual(proc._timeout, 300)


class TestImageProcessorErrorHandling(unittest.TestCase):
    """Tests for error handling in the image processor."""

    def _make_processor(self):
        history = MagicMock(spec=HistoryManager)
        spoiler = MagicMock(spec=SpoilerManager)
        spoiler.get_settings.return_value = {}
        spoiler.generate_prompt_block.return_value = ""
        return ImageProcessor(
            ollama_host="http://localhost:11434",
            model="test",
            history_manager=history,
            spoiler_manager=spoiler,
        )

    def test_connection_error_returns_empty(self):
        proc = self._make_processor()

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False

        async def _raise_conn(*a, **kw):
            raise aiohttp.ClientConnectionError("refused")

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = _raise_conn
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_ctx)
        proc.backend._session = mock_session

        result = _run(proc._call_ollama("prompt", "img"))
        self.assertEqual(result, "")

    def test_timeout_retries_then_fails(self):
        proc = self._make_processor()

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False

        async def _raise_timeout(*a, **kw):
            raise asyncio.TimeoutError()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = _raise_timeout
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_ctx)
        proc.backend._session = mock_session

        result = _run(proc._call_ollama("prompt", "img"))
        self.assertEqual(result, "")


class TestImageProcessorBackendSwap(unittest.TestCase):
    """Tests for swapping LLM backends at runtime."""

    def _make_processor(self):
        history = MagicMock(spec=HistoryManager)
        spoiler = MagicMock(spec=SpoilerManager)
        spoiler.get_settings.return_value = {}
        spoiler.generate_prompt_block.return_value = ""
        return ImageProcessor(
            ollama_host="http://localhost:11434",
            model="test",
            history_manager=history,
            spoiler_manager=spoiler,
        )

    def test_default_backend_is_ollama(self):
        proc = self._make_processor()
        self.assertEqual(proc.backend.backend_type, "ollama")

    def test_backend_swap(self):
        from custom_components.gaming_assistant.llm_backend import OpenAICompatibleBackend
        proc = self._make_processor()

        new_backend = OpenAICompatibleBackend(
            host="https://api.openai.com",
            model="gpt-4o",
            api_key="test-key",
        )
        proc.backend = new_backend
        self.assertEqual(proc.backend.backend_type, "openai")
        self.assertEqual(proc.backend.model, "gpt-4o")


class TestPerceptualHash(unittest.TestCase):
    """Tests for perceptual hash and caching."""

    def test_phash_returns_int(self):
        # Test with a minimal valid image (1x1 JPEG)
        phash = ImageProcessor._compute_phash(b"\xff\xd8\xff\xe0invalid")
        self.assertIsInstance(phash, int)

    def test_phash_deterministic(self):
        data = b"test image data"
        h1 = ImageProcessor._compute_phash(data)
        h2 = ImageProcessor._compute_phash(data)
        self.assertEqual(h1, h2)

    def test_hamming_distance(self):
        self.assertEqual(ImageProcessor._hamming_distance(0b1010, 0b1010), 0)
        self.assertEqual(ImageProcessor._hamming_distance(0b1010, 0b0101), 4)
        self.assertEqual(ImageProcessor._hamming_distance(0b1111, 0b1110), 1)


if __name__ == "__main__":
    unittest.main()
