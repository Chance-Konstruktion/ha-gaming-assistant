"""Camera watcher management for the Gaming Assistant.

Drives continuous capture from Home Assistant ``camera.*`` entities: each
watcher is an async task that grabs a snapshot every analysis interval,
resolves the effective game hint / source type, and feeds the frame into the
coordinator's image queue.

This is a collaborator of :class:`GamingAssistantCoordinator`. It owns the
set of active watchers and reaches back through the coordinator for shared
services (image queue, prompt packs, the data-refresh hook, and the
``gaming_mode`` flag).
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)

# Stop a watcher that keeps failing to grab frames, so a removed/broken
# camera entity does not spin forever.
MAX_CONSECUTIVE_ERRORS = 10


class CameraWatcher:
    """Owns active camera watchers and their capture loops."""

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        self.coord = coordinator
        # entity_id → {task, cancel_event, game_hint, client_type, interval}
        self._watchers: dict[str, dict[str, Any]] = {}

    # -- properties ----------------------------------------------------------

    @property
    def has_active(self) -> bool:
        """Whether any camera watcher is currently running."""
        return bool(self._watchers)

    @property
    def active_camera_watchers(self) -> dict[str, dict]:
        """Return info about all active camera watchers."""
        return {
            entity_id: {
                "game_hint": info["game_hint"],
                "client_type": info["client_type"],
                "interval": info["interval"],
            }
            for entity_id, info in self._watchers.items()
        }

    # -- lifecycle -----------------------------------------------------------

    async def async_watch(
        self,
        entity_id: str,
        game_hint: str = "",
        client_type: str = "console",
        interval: int = 0,
    ) -> None:
        """Start continuous capture from a HA camera entity.

        Uses the configured analysis interval if *interval* is 0.
        """
        if interval <= 0:
            interval = self.coord.analysis_interval

        # Stop existing watcher for this entity if running.
        if entity_id in self._watchers:
            await self.async_stop(entity_id)

        cancel_event = asyncio.Event()
        task = self.coord.hass.async_create_task(
            self._watch_loop(entity_id, game_hint, client_type, interval, cancel_event)
        )

        self._watchers[entity_id] = {
            "task": task,
            "cancel_event": cancel_event,
            "game_hint": game_hint,
            "client_type": client_type,
            "interval": interval,
        }
        self.coord._gaming_mode = True
        _LOGGER.info(
            "Camera watcher started: %s (game=%s, interval=%ds)",
            entity_id, game_hint or "auto", interval,
        )
        self.coord._notify_update()

    async def async_stop(self, entity_id: str = "") -> None:
        """Stop camera watcher(s). Empty entity_id stops all."""
        targets = [entity_id] if entity_id else list(self._watchers.keys())

        for eid in targets:
            watcher = self._watchers.pop(eid, None)
            if watcher:
                watcher["cancel_event"].set()
                watcher["task"].cancel()
                _LOGGER.info("Camera watcher stopped: %s", eid)

        if not self._watchers:
            self.coord._gaming_mode = False

        self.coord._notify_update()

    async def _watch_loop(
        self,
        entity_id: str,
        game_hint: str,
        client_type: str,
        interval: int,
        cancel_event: asyncio.Event,
    ) -> None:
        """Periodically grab snapshots from a HA camera entity."""
        from homeassistant.components.camera import async_get_image

        consecutive_errors = 0

        while not cancel_event.is_set():
            try:
                image = await async_get_image(self.coord.hass, entity_id)
                image_bytes = image.content
                consecutive_errors = 0

                # Use dynamic game hint: explicit param > persistent default.
                effective_hint = game_hint or self.coord.default_game_hint

                # Resolve client_type based on source_type setting:
                # - "console": always treat as digital game on screen
                # - "tabletop": always treat as physical game on table
                # - "auto": use prompt pack match to decide
                if self.coord.source_type == "auto":
                    effective_type = client_type
                    if effective_type == "console" and effective_hint:
                        pack = self.coord.pack_loader.find_by_keyword(effective_hint)
                        if not pack:
                            effective_type = "tabletop"
                else:
                    effective_type = self.coord.source_type

                metadata = {
                    "client_type": effective_type,
                    "source": entity_id,
                }
                if effective_hint:
                    metadata["window_title"] = effective_hint

                # Use entity_id as client_id (sanitise dots → underscores).
                client_id = entity_id.replace(".", "_")
                self.coord._client_metadata[client_id] = metadata

                self.coord._record_last_image(client_id, image_bytes)
                await self.coord._enqueue_image(client_id, image_bytes)

            except asyncio.CancelledError:
                return
            except Exception as err:
                consecutive_errors += 1
                _LOGGER.warning(
                    "Camera watcher %s error (%d/%d): %s",
                    entity_id, consecutive_errors, MAX_CONSECUTIVE_ERRORS, err,
                )
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    _LOGGER.error(
                        "Camera watcher %s stopped after %d consecutive errors",
                        entity_id, MAX_CONSECUTIVE_ERRORS,
                    )
                    self._watchers.pop(entity_id, None)
                    if not self._watchers:
                        self.coord._gaming_mode = False
                    self.coord._notify_update()
                    return

            # Wait for interval or cancellation (read current interval each time
            # so changes via the number entity take effect immediately).
            current_interval = self.coord.analysis_interval
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=current_interval)
                return  # cancel_event was set
            except asyncio.TimeoutError:
                pass  # interval elapsed, loop again
