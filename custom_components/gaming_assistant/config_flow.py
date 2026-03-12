"""Config flow for Gaming Assistant integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_OLLAMA_HOST,
    CONF_MODEL,
    CONF_INTERVAL,
    CONF_DEFAULT_SPOILER,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_MODEL,
    DEFAULT_INTERVAL,
    DEFAULT_SPOILER_LEVEL,
    SPOILER_LEVELS,
)

_LOGGER = logging.getLogger(__name__)

FALLBACK_MODELS = ["qwen2.5vl", "llava", "llava:13b", "bakllava", "llama3.2-vision"]


def _fetch_ollama_models(host: str) -> list[str] | None:
    """Fetch available models from Ollama (blocking – run in executor).

    Returns a sorted list of model names, or *None* if the server is
    unreachable (so the config flow can show a proper error).
    """
    try:
        import requests  # noqa: C0415

        resp = requests.get(f"{host.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        if models:
            _LOGGER.debug("Fetched %d models from Ollama: %s", len(models), models)
            return sorted(models)
        # Server reachable but no models pulled yet – return fallback list
        _LOGGER.warning("Ollama reachable but no models found – using fallback list")
        return FALLBACK_MODELS
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.warning("Could not reach Ollama at %s: %s", host, err)
        return None


def _schema_model_step(
    models: list[str], default_model: str, default_interval: int
) -> vol.Schema:
    if default_model not in models:
        models = [default_model, *models]
    return vol.Schema(
        {
            vol.Required(CONF_MODEL, default=default_model): vol.In(models),
            vol.Required(CONF_INTERVAL, default=default_interval): vol.All(
                int, vol.Range(min=5, max=120)
            ),
        }
    )


class GamingAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Three-step config flow: 1) host  2) model  3) spoiler defaults."""

    VERSION = 1

    def __init__(self) -> None:
        self._ollama_host: str = DEFAULT_OLLAMA_HOST
        self._models: list[str] = FALLBACK_MODELS
        self._model: str = DEFAULT_MODEL
        self._interval: int = DEFAULT_INTERVAL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1 – enter Ollama host URL."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_OLLAMA_HOST].rstrip("/")
            self._ollama_host = host

            models = await self.hass.async_add_executor_job(
                _fetch_ollama_models, host
            )

            if models is None:
                errors["base"] = "cannot_connect"
            else:
                self._models = models
                return await self.async_step_model()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_OLLAMA_HOST, default=self._ollama_host
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2 – pick model and analysis interval."""
        if user_input is not None:
            self._model = user_input[CONF_MODEL]
            self._interval = user_input[CONF_INTERVAL]
            return await self.async_step_spoiler()

        return self.async_show_form(
            step_id="model",
            data_schema=_schema_model_step(
                self._models, DEFAULT_MODEL, DEFAULT_INTERVAL
            ),
        )

    async def async_step_spoiler(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3 – configure default spoiler level."""
        if user_input is not None:
            return self.async_create_entry(
                title="Gaming Assistant",
                data={
                    CONF_OLLAMA_HOST: self._ollama_host,
                    CONF_MODEL: self._model,
                    CONF_INTERVAL: self._interval,
                    CONF_DEFAULT_SPOILER: user_input[CONF_DEFAULT_SPOILER],
                },
            )

        return self.async_show_form(
            step_id="spoiler",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEFAULT_SPOILER, default=DEFAULT_SPOILER_LEVEL
                    ): vol.In(SPOILER_LEVELS),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> GamingAssistantOptionsFlow:
        return GamingAssistantOptionsFlow()


class GamingAssistantOptionsFlow(config_entries.OptionsFlow):
    """Options flow – reconfigure model, interval, and spoiler defaults."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        current: dict[str, Any] = {
            **self.config_entry.data,
            **self.config_entry.options,
        }
        host = current.get(CONF_OLLAMA_HOST, DEFAULT_OLLAMA_HOST)

        models = await self.hass.async_add_executor_job(_fetch_ollama_models, host)
        if models is None:
            models = FALLBACK_MODELS

        default_model = current.get(CONF_MODEL, DEFAULT_MODEL)
        default_interval = current.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        default_spoiler = current.get(CONF_DEFAULT_SPOILER, DEFAULT_SPOILER_LEVEL)

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        if default_model not in models:
            models = [default_model, *models]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL, default=default_model): vol.In(models),
                    vol.Required(CONF_INTERVAL, default=default_interval): vol.All(
                        int, vol.Range(min=5, max=120)
                    ),
                    vol.Required(
                        CONF_DEFAULT_SPOILER, default=default_spoiler
                    ): vol.In(SPOILER_LEVELS),
                }
            ),
        )
