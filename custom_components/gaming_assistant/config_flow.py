"""Config flow for Gaming Assistant integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_AUTO_ANNOUNCE,
    CONF_CAMERA_ENTITY,
    CONF_DEFAULT_SPOILER,
    CONF_INTERVAL,
    CONF_MODEL,
    CONF_OLLAMA_HOST,
    CONF_TIMEOUT,
    CONF_TTS_ENTITY,
    CONF_TTS_TARGET,
    DEFAULT_AUTO_ANNOUNCE,
    DEFAULT_INTERVAL,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_SPOILER_LEVEL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    SPOILER_LEVELS,
)

_LOGGER = logging.getLogger(__name__)

FALLBACK_MODELS = ["qwen2.5vl", "llava", "llava:13b", "bakllava", "llama3.2-vision"]


def _fetch_ollama_models(host: str) -> list[str] | None:
    """Fetch available models from Ollama (blocking – run in executor)."""
    try:
        import requests

        resp = requests.get(f"{host.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        if models:
            return sorted(models)
        _LOGGER.warning("Ollama reachable but no models found – using fallback list")
        return FALLBACK_MODELS
    except Exception as err:
        _LOGGER.warning("Could not reach Ollama at %s: %s", host, err)
        return None


def _schema_model_step(
    models: list[str],
    default_model: str,
    default_interval: int,
    default_timeout: int = DEFAULT_TIMEOUT,
) -> vol.Schema:
    if default_model not in models:
        models = [default_model, *models]
    return vol.Schema(
        {
            vol.Required(CONF_MODEL, default=default_model): vol.In(models),
            vol.Required(CONF_INTERVAL, default=default_interval): vol.All(
                int, vol.Range(min=5, max=120)
            ),
            vol.Required(CONF_TIMEOUT, default=default_timeout): vol.All(
                int, vol.Range(min=10, max=300)
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
        self._timeout: int = DEFAULT_TIMEOUT
        self._spoiler_level: str = DEFAULT_SPOILER_LEVEL
        self._camera_entity: str = ""

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
        """Step 2 – pick model, analysis interval, and timeout."""
        if user_input is not None:
            self._model = user_input[CONF_MODEL]
            self._interval = user_input[CONF_INTERVAL]
            self._timeout = user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
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
            self._spoiler_level = user_input[CONF_DEFAULT_SPOILER]
            return await self.async_step_camera()

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

    async def async_step_camera(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 4 – optionally select a camera entity to auto-watch."""
        if user_input is not None:
            self._camera_entity = user_input.get(CONF_CAMERA_ENTITY, "")
            return await self.async_step_tts()

        # Build list of available camera entities
        camera_entities = self._get_camera_entities()

        schema_fields: dict = {}
        if camera_entities:
            options = {"": "— No camera (use external worker) —"}
            options.update({eid: eid for eid in sorted(camera_entities)})
            schema_fields[vol.Optional(CONF_CAMERA_ENTITY, default="")] = vol.In(
                options
            )
        else:
            schema_fields[vol.Optional(CONF_CAMERA_ENTITY, default="")] = str

        return self.async_show_form(
            step_id="camera",
            data_schema=vol.Schema(schema_fields),
        )

    async def async_step_tts(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 5 – optionally configure TTS for automatic tip announcements."""
        if user_input is not None:
            tts_entity = user_input.get(CONF_TTS_ENTITY, "")
            tts_target = user_input.get(CONF_TTS_TARGET, "")
            auto_announce = user_input.get(CONF_AUTO_ANNOUNCE, DEFAULT_AUTO_ANNOUNCE)
            return self.async_create_entry(
                title="Gaming Assistant",
                data={
                    CONF_OLLAMA_HOST: self._ollama_host,
                    CONF_MODEL: self._model,
                    CONF_INTERVAL: self._interval,
                    CONF_TIMEOUT: self._timeout,
                    CONF_DEFAULT_SPOILER: self._spoiler_level,
                    CONF_CAMERA_ENTITY: self._camera_entity,
                    CONF_TTS_ENTITY: tts_entity,
                    CONF_TTS_TARGET: tts_target,
                    CONF_AUTO_ANNOUNCE: auto_announce,
                },
            )

        # Build list of available TTS entities
        tts_entities = self._get_entities_by_domain("tts")
        media_players = self._get_entities_by_domain("media_player")

        schema_fields: dict = {}

        # TTS engine entity (e.g. tts.piper)
        if tts_entities:
            tts_options = {"": "— No TTS (skip) —"}
            tts_options.update({eid: eid for eid in sorted(tts_entities)})
            schema_fields[vol.Optional(CONF_TTS_ENTITY, default="")] = vol.In(
                tts_options
            )
        else:
            schema_fields[vol.Optional(CONF_TTS_ENTITY, default="")] = str

        # Target media_player (speaker)
        if media_players:
            mp_options = {"": "— Default speaker —"}
            mp_options.update({eid: eid for eid in sorted(media_players)})
            schema_fields[vol.Optional(CONF_TTS_TARGET, default="")] = vol.In(
                mp_options
            )
        else:
            schema_fields[vol.Optional(CONF_TTS_TARGET, default="")] = str

        # Auto-announce toggle
        schema_fields[
            vol.Optional(CONF_AUTO_ANNOUNCE, default=DEFAULT_AUTO_ANNOUNCE)
        ] = bool

        return self.async_show_form(
            step_id="tts",
            data_schema=vol.Schema(schema_fields),
        )

    def _get_camera_entities(self) -> list[str]:
        """Return all camera entity IDs registered in HA."""
        return self._get_entities_by_domain("camera")

    def _get_entities_by_domain(self, domain: str) -> list[str]:
        """Return all entity IDs for a given domain registered in HA."""
        registry = er.async_get(self.hass)
        return [
            entry.entity_id
            for entry in registry.entities.values()
            if entry.domain == domain and not entry.disabled
        ]

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> GamingAssistantOptionsFlow:
        return GamingAssistantOptionsFlow()


class GamingAssistantOptionsFlow(config_entries.OptionsFlow):
    """Options flow – reconfigure model and camera (setup-level settings only)."""

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
        default_camera = current.get(CONF_CAMERA_ENTITY, "")
        default_tts = current.get(CONF_TTS_ENTITY, "")
        default_tts_target = current.get(CONF_TTS_TARGET, "")
        default_auto_announce = current.get(CONF_AUTO_ANNOUNCE, DEFAULT_AUTO_ANNOUNCE)

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        if default_model not in models:
            models = [default_model, *models]

        # Build entity options
        registry = er.async_get(self.hass)

        def _entity_options(domain: str, empty_label: str) -> dict[str, str]:
            entities = [
                e.entity_id for e in registry.entities.values()
                if e.domain == domain and not e.disabled
            ]
            opts = {"": empty_label}
            opts.update({eid: eid for eid in sorted(entities)})
            return opts

        camera_options = _entity_options("camera", "— No camera (use external worker) —")
        tts_options = _entity_options("tts", "— No TTS —")
        mp_options = _entity_options("media_player", "— Default speaker —")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL, default=default_model): vol.In(models),
                    vol.Optional(
                        CONF_CAMERA_ENTITY, default=default_camera
                    ): vol.In(camera_options),
                    vol.Optional(
                        CONF_TTS_ENTITY, default=default_tts
                    ): vol.In(tts_options),
                    vol.Optional(
                        CONF_TTS_TARGET, default=default_tts_target
                    ): vol.In(mp_options),
                    vol.Optional(
                        CONF_AUTO_ANNOUNCE, default=default_auto_announce
                    ): bool,
                }
            ),
        )
