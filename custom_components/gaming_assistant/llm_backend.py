"""LLM Backend Abstraction Layer.

Provides a unified interface for different LLM providers so the
Gaming Assistant can work with local Ollama, OpenAI-compatible APIs
(GPT-4o, Gemini, DeepSeek, LM Studio, etc.), or any future backend.

Design goals:
- HACS-friendly: no heavy dependencies (requests only)
- Drop-in replacement for direct Ollama calls in ImageProcessor
- Privacy-first: Cloud backends receive only text by default;
  image sending is opt-in per backend config
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

# Default generation parameters
DEFAULT_TEMPERATURE = 0.4
DEFAULT_NUM_PREDICT = 200
DEFAULT_TIMEOUT = 60
DEFAULT_RETRY_DELAY = 5
DEFAULT_RATE_LIMIT_RPM = 30


class LLMResponse:
    """Wrapper for LLM responses."""

    __slots__ = ("text", "model", "usage", "raw")

    def __init__(
        self,
        text: str,
        model: str = "",
        usage: dict[str, int] | None = None,
        raw: dict | None = None,
    ) -> None:
        self.text = text
        self.model = model
        self.usage = usage or {}
        self.raw = raw


class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    def __init__(
        self,
        host: str,
        model: str,
        timeout: int = DEFAULT_TIMEOUT,
        api_key: str = "",
        allow_images: bool = True,
        rate_limit_rpm: int = 0,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self.allow_images = allow_images
        self.rate_limit_rpm = max(0, rate_limit_rpm)
        self._request_timestamps: list[float] = []

    async def _apply_rate_limit(self) -> None:
        """Throttle request rate for cloud APIs (best effort)."""
        if self.rate_limit_rpm <= 0:
            return
        now = time.monotonic()
        window_start = now - 60.0
        self._request_timestamps = [
            ts for ts in self._request_timestamps
            if ts >= window_start
        ]
        if len(self._request_timestamps) >= self.rate_limit_rpm:
            wait_s = max(0.0, 60.0 - (now - self._request_timestamps[0]))
            if wait_s > 0:
                _LOGGER.info(
                    "Rate limit reached (%d rpm), waiting %.1fs",
                    self.rate_limit_rpm, wait_s,
                )
                await asyncio.sleep(wait_s)
        self._request_timestamps.append(time.monotonic())

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Return the backend type identifier."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        image_b64: str = "",
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_NUM_PREDICT,
    ) -> LLMResponse:
        """Generate a response from the LLM."""

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_NUM_PREDICT,
    ) -> LLMResponse:
        """Generate a text-only response (no image)."""

    async def list_models(self) -> list[str]:
        """List available models. Override in subclasses."""
        return []

    @staticmethod
    def clean_response(text: str) -> str:
        """Strip incomplete trailing sentences caused by token limit cutoff."""
        if not text:
            return text
        if text[-1] in ".!?)\"'":
            return text
        for i in range(len(text) - 1, -1, -1):
            if text[i] in ".!?)":
                return text[: i + 1]
        return text


class OllamaBackend(LLMBackend):
    """Backend for local Ollama instances."""

    @property
    def backend_type(self) -> str:
        return "ollama"

    async def generate(
        self,
        prompt: str,
        image_b64: str = "",
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_NUM_PREDICT,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if image_b64:
            payload["images"] = [image_b64]

        return await self._call(payload)

    async def generate_text(
        self,
        prompt: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_NUM_PREDICT,
    ) -> LLMResponse:
        return await self.generate(prompt, "", temperature, max_tokens)

    async def list_models(self) -> list[str]:
        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    f"{self.host}/api/tags", timeout=5
                ),
            )
            resp.raise_for_status()
            return sorted(m["name"] for m in resp.json().get("models", []))
        except Exception as err:
            _LOGGER.warning("Could not fetch Ollama models: %s", err)
            return []

    async def _call(self, payload: dict) -> LLMResponse:
        url = f"{self.host}/api/generate"
        loop = asyncio.get_event_loop()

        for attempt in range(2):
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.post(
                        url, json=payload, timeout=self.timeout
                    ),
                )
                response.raise_for_status()
                data = response.json()
                text = self.clean_response(data.get("response", "").strip())
                return LLMResponse(
                    text=text,
                    model=self.model,
                    raw=data,
                )
            except requests.exceptions.Timeout:
                _LOGGER.warning(
                    "Ollama timeout (attempt %d/2), retrying in %ds",
                    attempt + 1,
                    DEFAULT_RETRY_DELAY * (2 ** attempt),
                )
                if attempt == 0:
                    await asyncio.sleep(DEFAULT_RETRY_DELAY * (2 ** attempt))
            except requests.exceptions.ConnectionError:
                _LOGGER.error("Cannot reach Ollama at %s", self.host)
                return LLMResponse(text="")
            except Exception as err:
                _LOGGER.exception("Ollama call failed: %s", err)
                return LLMResponse(text="")

        _LOGGER.error("Ollama request failed after retries")
        return LLMResponse(text="")


class OpenAICompatibleBackend(LLMBackend):
    """Backend for OpenAI-compatible APIs.

    Works with: OpenAI GPT-4o, Google Gemini (via OpenAI compat),
    DeepSeek, LM Studio, Groq, Together AI, Fireworks, etc.
    """

    @property
    def backend_type(self) -> str:
        return "openai"

    async def generate(
        self,
        prompt: str,
        image_b64: str = "",
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_NUM_PREDICT,
    ) -> LLMResponse:
        messages = self._build_messages(prompt, image_b64)
        return await self._call(messages, temperature, max_tokens)

    async def generate_text(
        self,
        prompt: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_NUM_PREDICT,
    ) -> LLMResponse:
        return await self.generate(prompt, "", temperature, max_tokens)

    async def list_models(self) -> list[str]:
        loop = asyncio.get_event_loop()
        headers = self._headers()
        try:
            resp = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    f"{self.host}/v1/models",
                    headers=headers,
                    timeout=5,
                ),
            )
            resp.raise_for_status()
            data = resp.json()
            return sorted(m["id"] for m in data.get("data", []))
        except Exception as err:
            _LOGGER.warning("Could not fetch models from %s: %s", self.host, err)
            return []

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_messages(
        self, prompt: str, image_b64: str = ""
    ) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": prompt}]

        if image_b64 and self.allow_images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}",
                    },
                }
            )

        return [{"role": "user", "content": content}]

    async def _call(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        url = f"{self.host}/v1/chat/completions"
        headers = self._headers()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        loop = asyncio.get_event_loop()
        await self._apply_rate_limit()

        for attempt in range(2):
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=self.timeout,
                    ),
                )
                response.raise_for_status()
                data = response.json()

                text = ""
                choices = data.get("choices", [])
                if choices:
                    text = (
                        choices[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )

                usage = data.get("usage", {})

                return LLMResponse(
                    text=self.clean_response(text),
                    model=data.get("model", self.model),
                    usage={
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get(
                            "completion_tokens", 0
                        ),
                        "total_tokens": usage.get("total_tokens", 0),
                    },
                    raw=data,
                )
            except requests.exceptions.Timeout:
                _LOGGER.warning(
                    "OpenAI-compatible API timeout (attempt %d/2), retrying in %ds",
                    attempt + 1,
                    DEFAULT_RETRY_DELAY * (2 ** attempt),
                )
                if attempt == 0:
                    await asyncio.sleep(DEFAULT_RETRY_DELAY * (2 ** attempt))
            except requests.exceptions.ConnectionError:
                _LOGGER.error(
                    "Cannot reach API at %s", self.host
                )
                return LLMResponse(text="")
            except Exception as err:
                _LOGGER.exception("API call failed: %s", err)
                return LLMResponse(text="")

        _LOGGER.error("API request failed after retries")
        return LLMResponse(text="")


# -- Factory -----------------------------------------------------------------

# Backend type string → class mapping
BACKEND_TYPES = {
    "ollama": OllamaBackend,
    "openai": OpenAICompatibleBackend,
}

# Well-known provider presets: name → (host, default_model, needs_api_key)
PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "ollama": {
        "host": "http://localhost:11434",
        "model": "qwen2.5vl",
        "api_key_required": False,
        "backend": "ollama",
        "allow_images": True,
        "description": "Local Ollama (default)",
    },
    "lm_studio": {
        "host": "http://localhost:1234",
        "model": "",
        "api_key_required": False,
        "backend": "openai",
        "allow_images": True,
        "description": "LM Studio (local)",
    },
    "openai": {
        "host": "https://api.openai.com",
        "model": "gpt-4o",
        "api_key_required": True,
        "backend": "openai",
        "allow_images": True,
        "rate_limit_rpm": DEFAULT_RATE_LIMIT_RPM,
        "description": "OpenAI GPT-4o (cloud, paid)",
    },
    "gemini": {
        "host": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "api_key_required": True,
        "backend": "openai",
        "allow_images": True,
        "rate_limit_rpm": DEFAULT_RATE_LIMIT_RPM,
        "description": "Google Gemini (cloud, free tier available)",
    },
    "deepseek": {
        "host": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_required": True,
        "backend": "openai",
        "allow_images": False,
        "rate_limit_rpm": DEFAULT_RATE_LIMIT_RPM,
        "description": "DeepSeek (cloud, text-only strategy)",
    },
    "groq": {
        "host": "https://api.groq.com/openai",
        "model": "llama-3.3-70b-versatile",
        "api_key_required": True,
        "backend": "openai",
        "allow_images": False,
        "rate_limit_rpm": DEFAULT_RATE_LIMIT_RPM,
        "description": "Groq (cloud, fast inference)",
    },
}


def create_backend(
    backend_type: str = "ollama",
    host: str = "",
    model: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    api_key: str = "",
    allow_images: bool = True,
    provider: str = "",
    rate_limit_rpm: int = 0,
) -> LLMBackend:
    """Create an LLM backend instance.

    Use *provider* to pick from PROVIDER_PRESETS (e.g. "openai", "gemini"),
    or specify *backend_type* + *host* + *model* manually.
    """
    # Apply preset if provider is given
    if provider and provider in PROVIDER_PRESETS:
        preset = PROVIDER_PRESETS[provider]
        backend_type = preset["backend"]
        host = host or preset["host"]
        model = model or preset["model"]
        allow_images = preset.get("allow_images", True)
        if not rate_limit_rpm and preset.get("rate_limit_rpm"):
            rate_limit_rpm = int(preset["rate_limit_rpm"])

    cls = BACKEND_TYPES.get(backend_type, OllamaBackend)
    return cls(
        host=host or "http://localhost:11434",
        model=model or "qwen2.5vl",
        timeout=timeout,
        api_key=api_key,
        allow_images=allow_images,
        rate_limit_rpm=rate_limit_rpm,
    )
