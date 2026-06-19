"""Sensor platform for Gaming Assistant."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gaming Assistant sensors."""
    coordinator: GamingAssistantCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        GamingAssistantTipSensor(coordinator),
        GamingAssistantStatusSensor(coordinator),
        GamingAssistantHistorySensor(coordinator),
        GamingAssistantLatencySensor(coordinator),
        GamingAssistantErrorCountSensor(coordinator),
        GamingAssistantLastErrorSensor(coordinator),
        GamingAssistantFramesProcessedSensor(coordinator),
        GamingAssistantLastAnalysisSensor(coordinator),
        GamingAssistantActiveWatchersSensor(coordinator),
        GamingAssistantRegisteredWorkersSensor(coordinator),
        GamingAssistantSessionSummarySensor(coordinator),
        GamingAssistantAgentActionSensor(coordinator),
        GamingAssistantPerceptionSensor(coordinator),
        GamingAssistantStrategySensor(coordinator),
        GamingAssistantChessSensor(coordinator),
    ])


class GamingAssistantTipSensor(CoordinatorEntity, SensorEntity):
    """Shows the latest AI gaming tip."""

    _attr_name = "Gaming Assistant Tip"
    _attr_unique_id = "gaming_assistant_tip"
    _attr_icon = "mdi:robot"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        tip = self._coordinator.tip
        # HA state has a 255-char limit; truncate for state, full tip in attributes
        if len(tip) > 250:
            return tip[:247] + "..."
        return tip

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "full_tip": self._coordinator.tip,
            "gaming_mode": self._coordinator.gaming_mode,
            "worker_status": self._coordinator.status,
            "game": self._coordinator.current_game,
        }


class GamingAssistantStatusSensor(CoordinatorEntity, SensorEntity):
    """Shows the current worker status."""

    _attr_name = "Gaming Assistant Status"
    _attr_unique_id = "gaming_assistant_status"
    _attr_icon = "mdi:information-outline"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        return self._coordinator.status

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "assistant_mode": self._coordinator.assistant_mode,
            "default_game_hint": self._coordinator.default_game_hint,
            "available_game_packs": self._coordinator.available_game_packs,
            "available_models": self._coordinator.data.get("available_models", []),
            "active_model": self._coordinator.active_model,
            "active_client_id": self._coordinator.data.get("active_client_id", ""),
            "clients": self._coordinator.data.get("clients", {}),
        }


class GamingAssistantHistorySensor(CoordinatorEntity, SensorEntity):
    """Shows tip history for the current session."""

    _attr_name = "Gaming Assistant History"
    _attr_unique_id = "gaming_assistant_history"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int:
        return self._coordinator.tip_count

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "recent_tips": self._coordinator.recent_tips,
            "current_game": self._coordinator.current_game,
            "client_id": self._coordinator.current_client_id,
        }


class GamingAssistantLatencySensor(CoordinatorEntity, SensorEntity):
    """Duration of the last analysis in seconds."""

    _attr_name = "Gaming Assistant Latency"
    _attr_unique_id = "gaming_assistant_latency"
    _attr_native_unit_of_measurement = "s"
    _attr_icon = "mdi:clock"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float:
        return self._coordinator.latency


class GamingAssistantErrorCountSensor(CoordinatorEntity, SensorEntity):
    """Number of errors since startup."""

    _attr_name = "Gaming Assistant Error Count"
    _attr_unique_id = "gaming_assistant_error_count"
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int:
        return self._coordinator.error_count


class GamingAssistantLastErrorSensor(CoordinatorEntity, SensorEntity):
    """Shows the most recent error message for easy diagnostics."""

    _attr_name = "Gaming Assistant Last Error"
    _attr_unique_id = "gaming_assistant_last_error"
    _attr_icon = "mdi:alert"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        msg = self._coordinator.last_error_message
        if not msg:
            return "ok"
        if len(msg) > 250:
            return msg[:247] + "..."
        return msg

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "error_type": self._coordinator.last_error_type,
            "timestamp": self._coordinator.last_error_timestamp,
            "error_count": self._coordinator.error_count,
            "full_message": self._coordinator.last_error_message,
        }


class GamingAssistantFramesProcessedSensor(CoordinatorEntity, SensorEntity):
    """Total number of frames analyzed."""

    _attr_name = "Gaming Assistant Frames Processed"
    _attr_unique_id = "gaming_assistant_frames_processed"
    _attr_icon = "mdi:image-multiple"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int:
        return self._coordinator.frames_processed


class GamingAssistantLastAnalysisSensor(CoordinatorEntity, SensorEntity):
    """Timestamp of the last successful analysis."""

    _attr_name = "Gaming Assistant Last Analysis"
    _attr_unique_id = "gaming_assistant_last_analysis"
    _attr_icon = "mdi:clock-check"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        return self._coordinator.last_analysis


class GamingAssistantActiveWatchersSensor(CoordinatorEntity, SensorEntity):
    """Number of active camera watchers."""

    _attr_name = "Gaming Assistant Active Watchers"
    _attr_unique_id = "gaming_assistant_active_watchers"
    _attr_icon = "mdi:camera-eye"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int:
        return len(self._coordinator.active_camera_watchers)

    @property
    def extra_state_attributes(self) -> dict:
        return {"watchers": self._coordinator.active_camera_watchers}


class GamingAssistantRegisteredWorkersSensor(CoordinatorEntity, SensorEntity):
    """Number of registered workers (auto-discovered via MQTT)."""

    _attr_name = "Gaming Assistant Workers"
    _attr_unique_id = "gaming_assistant_registered_workers"
    _attr_icon = "mdi:devices"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> int:
        return len(self._coordinator.registered_workers)

    @property
    def extra_state_attributes(self) -> dict:
        return {"workers": self._coordinator.registered_workers}


class GamingAssistantSessionSummarySensor(CoordinatorEntity, SensorEntity):
    """Shows the last session summary."""

    _attr_name = "Gaming Assistant Session Summary"
    _attr_unique_id = "gaming_assistant_session_summary"
    _attr_icon = "mdi:text-box-outline"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        summary = self._coordinator.last_summary
        if not summary:
            return "No summary yet"
        if len(summary) > 250:
            return summary[:247] + "..."
        return summary

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "full_summary": self._coordinator.last_summary,
            "game": self._coordinator.last_summary_game,
            "timestamp": self._coordinator.last_summary_timestamp,
        }


class GamingAssistantAgentActionSensor(CoordinatorEntity, SensorEntity):
    """Audit sensor for Agent Mode (Player 2) autonomous actions.

    State is the last decision status (``idle`` / ``published`` / ``no_op`` /
    ``error`` / ``auto_disabled``); attributes carry the full action, the
    published/failed counters, and the active button whitelist so autonomous
    play can be monitored and automated against from Home Assistant.
    """

    _attr_name = "Gaming Assistant Agent Action"
    _attr_unique_id = "gaming_assistant_agent_action"
    _attr_icon = "mdi:robot-outline"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        return self._coordinator.agent_last_action_status or "idle"

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "agent_mode": self._coordinator.agent_mode,
            "last_action": self._coordinator.agent_last_action,
            "timestamp": self._coordinator.agent_last_action_timestamp,
            "actions_published": self._coordinator.agent_actions_published,
            "actions_failed": self._coordinator.agent_actions_failed,
            "allowed_buttons": self._coordinator.agent_allowed_buttons or "all",
        }


class GamingAssistantPerceptionSensor(CoordinatorEntity, SensorEntity):
    """Tier 1 readout: scene-change magnitude of the last measured frame.

    State is the 0..1 scene-change value; attributes carry the coarse motion
    class and the count of frames the perception tier let skip the LLM, so
    the event-driven savings are visible from Home Assistant.
    """

    _attr_name = "Gaming Assistant Scene Change"
    _attr_unique_id = "gaming_assistant_scene_change"
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float:
        return self._coordinator.scene_change

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "frame_motion": self._coordinator.frame_motion,
            "frames_skipped": self._coordinator.frames_skipped,
            "frames_processed": self._coordinator.frames_processed,
        }


class GamingAssistantStrategySensor(CoordinatorEntity, SensorEntity):
    """Tier 3 readout: the current session-level strategic focus.

    State is the strategic note fed back down into the tactical prompts
    (``No focus yet`` when none); the full text and game are in attributes.
    """

    _attr_name = "Gaming Assistant Strategy"
    _attr_unique_id = "gaming_assistant_strategy"
    _attr_icon = "mdi:chess-queen"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        note = self._coordinator.strategy_note
        if not note:
            return "No focus yet"
        if len(note) > 250:
            return note[:247] + "..."
        return note

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "full_strategy": self._coordinator.strategy_note,
            "game": self._coordinator.current_game,
        }


class GamingAssistantChessSensor(CoordinatorEntity, SensorEntity):
    """Chess grounding readout: the suggested best move for the last board.

    State is the suggested move in SAN (``No board yet`` when none); the
    full grounded facts (material, eval, threats, flags) are in attributes.
    The engine runs inside Home Assistant — no extra server.
    """

    _attr_name = "Gaming Assistant Chess"
    _attr_unique_id = "gaming_assistant_chess"
    _attr_icon = "mdi:chess-king"

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        grounding = self._coordinator.chess_grounding
        if not grounding.get("valid"):
            return "No board yet"
        return grounding.get("best_move") or grounding.get("summary", "—")

    @property
    def extra_state_attributes(self) -> dict:
        g = self._coordinator.chess_grounding
        return {
            "available": g.get("available", False),
            "valid": g.get("valid", False),
            "summary": g.get("summary", ""),
            "side_to_move": g.get("side_to_move"),
            "best_move": g.get("best_move"),
            "eval_white_cp": g.get("eval_white_cp"),
            "material_cp": g.get("material_cp"),
            "phase": g.get("phase"),
            "legal_moves": g.get("legal_moves"),
            "is_check": g.get("is_check"),
            "is_checkmate": g.get("is_checkmate"),
            "captures": g.get("captures"),
            "checks": g.get("checks"),
            "fen": g.get("fen"),
            "error": g.get("error"),
        }
