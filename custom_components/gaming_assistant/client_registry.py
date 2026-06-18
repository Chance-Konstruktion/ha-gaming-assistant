"""Client / worker registry for the Gaming Assistant.

Tracks every capture agent and worker that talks to the integration over
MQTT: when each was first/last seen, its advertised metadata, online/offline
presence, and a per-client inactivity timer that flips ``gaming_mode`` off
when frames stop arriving.

This is a collaborator of :class:`GamingAssistantCoordinator`. It owns the
registry dictionaries and the inactivity timers, and reaches back through the
coordinator for the event loop, the current-game/-client pointers, the camera
watcher state, and the data-refresh hook.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)

# A client is considered inactive after 3 analysis intervals (min 30s).
INACTIVITY_MIN_SECONDS = 30


class ClientRegistry:
    """Owns worker/client registries and per-client inactivity timers."""

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        self.coord = coordinator
        self._registered_workers: dict[str, dict[str, Any]] = {}
        self._clients: dict[str, dict[str, Any]] = {}
        self._inactivity_timers: dict[str, Any] = {}  # client_id → TimerHandle
        self._active_client_id: str = ""

    # -- accessors -----------------------------------------------------------

    @property
    def registered_workers(self) -> dict[str, dict[str, Any]]:
        return self._registered_workers

    @property
    def clients(self) -> dict[str, dict[str, Any]]:
        return self._clients

    @property
    def active_client_id(self) -> str:
        return self._active_client_id

    def set_active(self, client_id: str) -> None:
        self._active_client_id = client_id

    # -- registration --------------------------------------------------------

    def register_worker(
        self, client_id: str, info: dict[str, Any] | None = None
    ) -> None:
        """Register or update a worker. Called automatically on MQTT activity."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._active_client_id = client_id
        if client_id in self._registered_workers:
            self._registered_workers[client_id]["last_seen"] = now
            if info:
                self._registered_workers[client_id].update(info)
        else:
            worker_info = {
                "name": info.get("name", client_id) if info else client_id,
                "type": info.get("type", "unknown") if info else "unknown",
                "platform": info.get("platform", "") if info else "",
                "version": info.get("version", "") if info else "",
                "first_seen": now,
                "last_seen": now,
            }
            if info:
                worker_info.update(
                    {k: v for k, v in info.items() if k not in worker_info}
                )
            self._registered_workers[client_id] = worker_info
            _LOGGER.info(
                "New worker registered: %s (%s)",
                client_id, worker_info.get("type"),
            )
        self.touch_client(client_id, info)
        self.coord._notify_update()

    def touch_client(
        self, client_id: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Update per-client runtime state and inactivity timer."""
        now_ts = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
        current = self._clients.get(client_id, {})
        meta = dict(current.get("meta", {}))
        if metadata:
            meta.update(metadata)
        client_state: dict[str, Any] = {
            "client_id": client_id,
            "last_seen": now_iso,
            "last_seen_ts": now_ts,
            "meta": meta,
            "last_game": current.get("last_game", ""),
        }
        # Backward compatibility: keep selected metadata mirrored at top-level
        # so older dashboards/templates continue to work after merge updates.
        client_state.update(meta)

        game = (meta.get("window_title") or meta.get("game") or "").strip()
        if game:
            client_state["last_game"] = game
            self.coord._current_game = game
        self._clients[client_id] = client_state
        self.coord._current_client_id = client_id
        self._active_client_id = client_id
        self._schedule_inactivity(client_id)

    def mark_presence(self, client_id: str, online: bool) -> None:
        """Update online/offline presence from a Last-Will status message."""
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
        if client_id in self._registered_workers:
            self._registered_workers[client_id]["online"] = online
            self._registered_workers[client_id]["last_seen"] = now_iso
        if client_id in self._clients:
            self._clients[client_id]["online"] = online

    # -- inactivity timers ---------------------------------------------------

    def _schedule_inactivity(self, client_id: str) -> None:
        """Reset the inactivity timer for a client."""
        handle = self._inactivity_timers.pop(client_id, None)
        if handle:
            handle.cancel()
        timeout = max(self.coord.analysis_interval * 3, INACTIVITY_MIN_SECONDS)
        self._inactivity_timers[client_id] = self.coord.hass.loop.call_later(
            timeout,
            lambda: self.coord.hass.async_create_task(
                self._handle_inactive(client_id)
            ),
        )

    async def _handle_inactive(self, client_id: str) -> None:
        """Mark client as inactive when no frames arrive for a while."""
        self._inactivity_timers.pop(client_id, None)
        client = self._clients.get(client_id)
        if client:
            age = time.time() - float(client.get("last_seen_ts", 0))
            if age < INACTIVITY_MIN_SECONDS:
                return
        if self._active_client_id != client_id:
            return
        if self.coord._camera_watcher.has_active:
            return
        self.coord._gaming_mode = False
        if self.coord._status != "error":
            self.coord._status = "idle"
        _LOGGER.info("Client %s inactive – switching gaming mode off", client_id)
        self.coord._notify_update()

    def cancel_timers(self) -> None:
        """Cancel and clear all pending inactivity timers."""
        for handle in self._inactivity_timers.values():
            handle.cancel()
        self._inactivity_timers.clear()
