"""Button platform for Gaming Assistant.

One-tap decisions for Agent Mode's optional per-action confirmation: the
buttons are only available while an action is waiting, so a dashboard shows
them exactly when there is something to confirm or reject.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GamingAssistantCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gaming Assistant button entities."""
    coordinator: GamingAssistantCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        AgentConfirmActionButton(coordinator),
        AgentRejectActionButton(coordinator),
    ])


class _PendingAgentActionButton(CoordinatorEntity, ButtonEntity):
    """Base for buttons that act on the action awaiting confirmation."""

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        return self._coordinator.agent_pending_action is not None


class AgentConfirmActionButton(_PendingAgentActionButton):
    """Send the pending Agent Mode action to the executor."""

    _attr_name = "Gaming Assistant Agent Confirm Action"
    _attr_unique_id = "gaming_assistant_agent_confirm_action"
    _attr_icon = "mdi:check-circle-outline"
    _attr_translation_key = "agent_confirm_action"

    async def async_press(self) -> None:
        await self._coordinator.async_confirm_agent_action()


class AgentRejectActionButton(_PendingAgentActionButton):
    """Drop the pending Agent Mode action."""

    _attr_name = "Gaming Assistant Agent Reject Action"
    _attr_unique_id = "gaming_assistant_agent_reject_action"
    _attr_icon = "mdi:close-circle-outline"
    _attr_translation_key = "agent_reject_action"

    async def async_press(self) -> None:
        await self._coordinator.async_reject_agent_action()
