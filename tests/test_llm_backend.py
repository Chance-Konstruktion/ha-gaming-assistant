"""Unit tests for the LLM Backend Abstraction Layer."""

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, patch

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

from custom_components.gaming_assistant.llm_backend import (
    LLMResponse,
    OllamaBackend,
    OpenAICompatibleBackend,
    PROVIDER_PRESETS,
    create_backend,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestLLMResponse(unittest.TestCase):
    """Tests for LLMResponse wrapper."""

    def test_basic_response(self):
        resp = LLMResponse(text="Hello", model="gpt-4o")
        self.assertEqual(resp.text, "Hello")
        self.assertEqual(resp.model, "gpt-4o")
        self.assertEqual(resp.usage, {})

    def test_response_with_usage(self):
        resp = LLMResponse(
            text="Hello",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
        self.assertEqual(resp.usage["prompt_tokens"], 10)


class TestOllamaBackend(unittest.TestCase):
    """Tests for the Ollama backend."""

    def test_backend_type(self):
        backend = OllamaBackend(host="http://localhost:11434", model="llava")
        self.assertEqual(backend.backend_type, "ollama")

    def test_generate_success(self):
        backend = OllamaBackend(host="http://localhost:11434", model="llava")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"response": "A chess tip."}

        with patch(
            "custom_components.gaming_assistant.llm_backend.requests.post",
            return_value=mock_response,
        ):
            result = _run(backend.generate("test prompt", "base64img"))
            self.assertEqual(result.text, "A chess tip.")

    def test_generate_text_only(self):
        backend = OllamaBackend(host="http://localhost:11434", model="llava")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"response": "Strategy tip."}

        with patch(
            "custom_components.gaming_assistant.llm_backend.requests.post",
            return_value=mock_response,
        ):
            result = _run(backend.generate_text("test prompt"))
            self.assertEqual(result.text, "Strategy tip.")

    def test_connection_error(self):
        import requests
        backend = OllamaBackend(host="http://localhost:11434", model="llava")

        with patch(
            "custom_components.gaming_assistant.llm_backend.requests.post",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            result = _run(backend.generate("prompt", "img"))
            self.assertEqual(result.text, "")

    def test_timeout_retries(self):
        import requests
        backend = OllamaBackend(host="http://localhost:11434", model="llava")

        with patch(
            "custom_components.gaming_assistant.llm_backend.requests.post",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            result = _run(backend.generate("prompt", "img"))
            self.assertEqual(result.text, "")

    def test_list_models(self):
        backend = OllamaBackend(host="http://localhost:11434", model="llava")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "models": [{"name": "llava"}, {"name": "qwen2.5vl"}]
        }

        with patch(
            "custom_components.gaming_assistant.llm_backend.requests.get",
            return_value=mock_response,
        ):
            models = _run(backend.list_models())
            self.assertIn("llava", models)
            self.assertIn("qwen2.5vl", models)


class TestOpenAIBackend(unittest.TestCase):
    """Tests for the OpenAI-compatible backend."""

    def test_backend_type(self):
        backend = OpenAICompatibleBackend(
            host="https://api.openai.com", model="gpt-4o", api_key="test"
        )
        self.assertEqual(backend.backend_type, "openai")

    def test_generate_success(self):
        backend = OpenAICompatibleBackend(
            host="https://api.openai.com", model="gpt-4o", api_key="test"
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Move knight to f3."}}],
            "model": "gpt-4o",
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 10,
                "total_tokens": 60,
            },
        }

        with patch(
            "custom_components.gaming_assistant.llm_backend.requests.post",
            return_value=mock_response,
        ):
            result = _run(backend.generate("test prompt"))
            self.assertEqual(result.text, "Move knight to f3.")
            self.assertEqual(result.usage["total_tokens"], 60)

    def test_image_not_sent_when_disabled(self):
        backend = OpenAICompatibleBackend(
            host="https://api.deepseek.com",
            model="deepseek-chat",
            api_key="test",
            allow_images=False,
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Tip"}}],
            "usage": {},
        }

        with patch(
            "custom_components.gaming_assistant.llm_backend.requests.post",
            return_value=mock_response,
        ) as mock_post:
            _run(backend.generate("prompt", "fake_base64_image"))
            call_payload = mock_post.call_args[1]["json"]
            # Messages should have only text content, no image
            content = call_payload["messages"][0]["content"]
            self.assertEqual(len(content), 1)
            self.assertEqual(content[0]["type"], "text")

    def test_headers_with_api_key(self):
        backend = OpenAICompatibleBackend(
            host="https://api.openai.com", model="gpt-4o", api_key="sk-test123"
        )
        headers = backend._headers()
        self.assertEqual(headers["Authorization"], "Bearer sk-test123")

    def test_headers_without_api_key(self):
        backend = OpenAICompatibleBackend(
            host="http://localhost:1234", model="local", api_key=""
        )
        headers = backend._headers()
        self.assertNotIn("Authorization", headers)


class TestCleanResponse(unittest.TestCase):
    """Tests for the static clean_response method."""

    def test_complete_sentence(self):
        text = "Move your knight to f3."
        self.assertEqual(OllamaBackend.clean_response(text), text)

    def test_truncated_sentence(self):
        text = "Move your knight to f3. This will help you control the cen"
        cleaned = OllamaBackend.clean_response(text)
        self.assertEqual(cleaned, "Move your knight to f3.")

    def test_empty(self):
        self.assertEqual(OllamaBackend.clean_response(""), "")

    def test_no_punctuation(self):
        text = "some text without punctuation"
        self.assertEqual(OllamaBackend.clean_response(text), text)


class TestCreateBackend(unittest.TestCase):
    """Tests for the create_backend factory."""

    def test_default_creates_ollama(self):
        backend = create_backend()
        self.assertEqual(backend.backend_type, "ollama")

    def test_provider_preset_openai(self):
        backend = create_backend(provider="openai", api_key="test")
        self.assertEqual(backend.backend_type, "openai")
        self.assertEqual(backend.model, "gpt-4o")
        self.assertIn("openai.com", backend.host)
        self.assertGreaterEqual(getattr(backend, "rate_limit_rpm", 0), 1)

    def test_provider_preset_gemini(self):
        backend = create_backend(provider="gemini", api_key="test")
        self.assertEqual(backend.backend_type, "openai")
        self.assertEqual(backend.model, "gemini-2.0-flash")

    def test_provider_preset_deepseek(self):
        backend = create_backend(provider="deepseek", api_key="test")
        self.assertFalse(backend.allow_images)

    def test_manual_backend_type(self):
        backend = create_backend(
            backend_type="openai",
            host="http://localhost:1234",
            model="custom-model",
        )
        self.assertEqual(backend.backend_type, "openai")
        self.assertEqual(backend.model, "custom-model")

    def test_provider_presets_exist(self):
        """All documented presets should exist."""
        for provider in ["ollama", "openai", "gemini", "deepseek", "lm_studio", "groq"]:
            self.assertIn(provider, PROVIDER_PRESETS)


class TestProviderPresets(unittest.TestCase):
    """Validate provider preset data structure."""

    def test_all_presets_have_required_fields(self):
        for pid, preset in PROVIDER_PRESETS.items():
            self.assertIn("host", preset, f"{pid} missing 'host'")
            self.assertIn("backend", preset, f"{pid} missing 'backend'")
            self.assertIn("api_key_required", preset, f"{pid} missing 'api_key_required'")
            self.assertIn("description", preset, f"{pid} missing 'description'")

    def test_backends_are_valid(self):
        from custom_components.gaming_assistant.llm_backend import BACKEND_TYPES
        for pid, preset in PROVIDER_PRESETS.items():
            self.assertIn(
                preset["backend"], BACKEND_TYPES,
                f"{pid} has invalid backend type: {preset['backend']}"
            )


if __name__ == "__main__":
    unittest.main()
