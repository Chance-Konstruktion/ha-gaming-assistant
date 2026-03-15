"""Unit tests for ImageProcessor – timeout configuration and metrics support."""

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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
]
for mod in _HA_MODULES:
    sys.modules.setdefault(mod, MagicMock())

from custom_components.gaming_assistant.image_processor import ImageProcessor
from custom_components.gaming_assistant.history import HistoryManager
from custom_components.gaming_assistant.spoiler import SpoilerManager
from custom_components.gaming_assistant.const import OLLAMA_TIMEOUT


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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

    def test_timeout_used_in_call(self):
        """Verify the configured timeout is passed to requests.post."""
        proc = self._make_processor(timeout=180)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"response": "Test tip"}

        with patch("custom_components.gaming_assistant.image_processor.requests.post", return_value=mock_response) as mock_post:
            result = _run(proc._call_ollama("test prompt", "base64data"))
            self.assertEqual(result, "Test tip")
            _, kwargs = mock_post.call_args
            self.assertEqual(kwargs["timeout"], 180)

    def test_timeout_default_used_in_call(self):
        """Default timeout should be OLLAMA_TIMEOUT."""
        proc = self._make_processor()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"response": "Tip"}

        with patch("custom_components.gaming_assistant.image_processor.requests.post", return_value=mock_response) as mock_post:
            _run(proc._call_ollama_text("prompt"))
            _, kwargs = mock_post.call_args
            self.assertEqual(kwargs["timeout"], OLLAMA_TIMEOUT)

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
        import requests
        proc = self._make_processor()
        with patch(
            "custom_components.gaming_assistant.image_processor.requests.post",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            result = _run(proc._call_ollama("prompt", "img"))
            self.assertEqual(result, "")

    def test_timeout_retries_then_fails(self):
        import requests
        proc = self._make_processor()
        with patch(
            "custom_components.gaming_assistant.image_processor.requests.post",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            result = _run(proc._call_ollama("prompt", "img"))
            self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
