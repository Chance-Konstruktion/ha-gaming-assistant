"""Conversation agent for Gaming Assistant – voice control via HA Assist."""
from __future__ import annotations

import logging
import re

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ASSISTANT_MODES, DOMAIN, SPOILER_LEVELS
from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Gaming Assistant conversation agent."""
    coordinator: GamingAssistantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GamingAssistantConversationEntity(coordinator, entry)])


class GamingAssistantConversationEntity(
    conversation.ConversationEntity,
):
    """Conversation agent that translates voice commands into Gaming Assistant actions."""

    _attr_has_entity_name = True
    _attr_name = "Gaming Assistant"

    def __init__(
        self,
        coordinator: GamingAssistantCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_conversation"

    @property
    def supported_languages(self) -> list[str] | str:
        """Return wildcard – Ollama handles any language."""
        return conversation.MATCH_ALL

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a voice/text command from HA Assist."""
        text = (user_input.text or "").strip()
        if not text:
            return self._respond(
                "I didn't catch that. Could you repeat?", user_input
            )

        intent_response = await self._async_try_intent(text)
        if intent_response is not None:
            return self._respond(intent_response, user_input)

        # Fall through: treat as a free-form question via the ask pipeline
        answer = await self.coordinator.async_ask(question=text)
        if answer:
            return self._respond(answer, user_input)

        return self._respond(
            "Sorry, I couldn't generate an answer right now. "
            "Please check that Ollama is running.",
            user_input,
        )

    # ------------------------------------------------------------------
    # Intent matching – maps common voice commands to service calls
    # ------------------------------------------------------------------

    _MODE_PATTERN = re.compile(
        r"(?:set|change|switch|wechsel[en]*|ändere?).*?"
        r"(?:mode?|modus)\s*(?:to|auf|zu|in)?\s*"
        r"(coach|co-?play(?:er)?|mitspieler|opponent|gegner|analyst)",
        re.IGNORECASE,
    )

    _SPOILER_PATTERN = re.compile(
        r"(?:set|change|switch|wechsel[en]*|ändere?).*?"
        r"spoiler\s*(?:level)?\s*(?:to|auf|zu)?\s*"
        r"(none|keins?|low|niedrig|medium|mittel|high|hoch)",
        re.IGNORECASE,
    )

    _START_PATTERN = re.compile(
        r"^(?:start|begin|starte?|los)\b",
        re.IGNORECASE,
    )

    _STOP_PATTERN = re.compile(
        r"^(?:stop|pause|halt|stopp?e?)\b",
        re.IGNORECASE,
    )

    _TIP_PATTERN = re.compile(
        r"(?:current|latest|last|letzter?|aktueller?)\s*(?:tip|tipp|hinweis)",
        re.IGNORECASE,
    )

    _SUMMARY_PATTERN = re.compile(
        r"(?:session|sitzung)?\s*(?:summary|zusammenfassung)",
        re.IGNORECASE,
    )

    _ANALYZE_PATTERN = re.compile(
        r"^(?:analyze|analyse|analysiere?|screenshot|scan)\b",
        re.IGNORECASE,
    )

    _MODE_MAP: dict[str, str] = {
        "coach": "coach",
        "coplay": "coplay",
        "coplayer": "coplay",
        "co-player": "coplay",
        "co-play": "coplay",
        "mitspieler": "coplay",
        "opponent": "opponent",
        "gegner": "opponent",
        "analyst": "analyst",
    }

    _SPOILER_MAP: dict[str, str] = {
        "none": "none",
        "kein": "none",
        "keins": "none",
        "low": "low",
        "niedrig": "low",
        "medium": "medium",
        "mittel": "medium",
        "high": "high",
        "hoch": "high",
    }

    async def _async_try_intent(self, text: str) -> str | None:
        """Try to match text to a known command. Returns response or None."""

        # -- Set mode --
        m = self._MODE_PATTERN.search(text)
        if m:
            raw = m.group(1).lower().strip()
            mode = self._MODE_MAP.get(raw)
            if mode and mode in ASSISTANT_MODES:
                self.coordinator.set_assistant_mode(mode)
                return f"Assistant mode changed to {mode}."

        # -- Set spoiler level --
        m = self._SPOILER_PATTERN.search(text)
        if m:
            raw = m.group(1).lower().strip()
            level = self._SPOILER_MAP.get(raw)
            if level and level in SPOILER_LEVELS:
                self.coordinator.set_default_spoiler_level(level)
                return f"Spoiler level set to {level}."

        # -- Start --
        if self._START_PATTERN.search(text):
            await self.coordinator.hass.services.async_call(
                DOMAIN, "start", {}
            )
            return "Gaming Assistant started."

        # -- Stop --
        if self._STOP_PATTERN.search(text):
            await self.coordinator.hass.services.async_call(
                DOMAIN, "stop", {}
            )
            return "Gaming Assistant stopped."

        # -- Current tip --
        if self._TIP_PATTERN.search(text):
            tip = self.coordinator.tip
            if tip and tip != "Waiting for tips...":
                return tip
            return "No tip available yet."

        # -- Session summary --
        if self._SUMMARY_PATTERN.search(text):
            summary = self.coordinator.last_summary
            if summary:
                return summary
            return "No session summary available yet."

        # -- Analyze now --
        if self._ANALYZE_PATTERN.search(text):
            await self.coordinator.hass.services.async_call(
                DOMAIN, "analyze", {}
            )
            return "Analyzing current screen..."

        return None

    # ------------------------------------------------------------------

    @staticmethod
    def _respond(
        text: str,
        user_input: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        """Build a ConversationResult from a plain-text answer."""
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(text)
        return conversation.ConversationResult(
            response=response,
            conversation_id=user_input.conversation_id,
        )
