"""Analysis pipeline for the Gaming Assistant.

Owns the integration's hot path: a bounded image queue with a single
sequential worker, the per-frame Tier 1 → Tier 2 → Tier 3 orchestration that
turns a captured frame into a coaching tip, and the opt-in Agent Mode action
publishing built on top of it.

This is a collaborator of :class:`GamingAssistantCoordinator`. It owns the
queue, the worker task, and the processing lock, and reaches back through the
coordinator for all shared runtime state (current game/client, status, tip and
metrics counters) and services (perception, strategy, the image processor, the
session tracker, the event bus, and the data-refresh hook) — mirroring how the
camera watcher, MQTT router, and session tracker collaborators are wired.

The pipeline writes back onto the coordinator (``self.coord._x``) deliberately:
the coordinator remains the single source of truth that the entities and the
diagnostics sensors read from, exactly as before this logic was extracted.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from .const import AGENT_ACTION_MIN_INTERVAL, EVENT_AGENT_ACTION
from . import tip_filter

if TYPE_CHECKING:
    from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)


class AnalysisPipeline:
    """Owns the image queue, the per-frame analysis, and Agent Mode actions."""

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        self.coord = coordinator
        self._process_lock = asyncio.Lock()
        self._image_queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue(maxsize=3)
        self._image_worker_task: asyncio.Task | None = None

    # -- queue / worker ------------------------------------------------------

    def _ensure_image_worker(self) -> None:
        """Ensure the image queue worker is running."""
        if self._image_worker_task and not self._image_worker_task.done():
            return
        self._image_worker_task = self.coord.hass.async_create_task(
            self._image_worker_loop()
        )

    async def _enqueue_image(self, client_id: str, image_bytes: bytes) -> None:
        """Enqueue image with bounded backpressure (drop oldest when full)."""
        self._ensure_image_worker()
        if self._image_queue.full():
            try:
                dropped_client, _ = self._image_queue.get_nowait()
                self._image_queue.task_done()
                _LOGGER.debug(
                    "Image queue full. Dropped oldest frame from %s", dropped_client
                )
            except asyncio.QueueEmpty:
                pass
        await self._image_queue.put((client_id, image_bytes))

    async def _image_worker_loop(self) -> None:
        """Sequentially process images from queue."""
        while True:
            client_id, image_bytes = await self._image_queue.get()
            _LOGGER.debug(
                "Image worker: processing %s (queue=%d/%d)",
                client_id, self._image_queue.qsize(), self._image_queue.maxsize,
            )
            try:
                await self._process_image(client_id, image_bytes)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.debug("Image worker: item failed, continuing", exc_info=True)
            finally:
                self._image_queue.task_done()

    def drain_queue(self) -> None:
        """Drop any queued frames (called when the assistant is stopped)."""
        while not self._image_queue.empty():
            try:
                self._image_queue.get_nowait()
                self._image_queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def cancel_worker(self) -> None:
        """Cancel the queue worker task (called on shutdown)."""
        if self._image_worker_task and not self._image_worker_task.done():
            self._image_worker_task.cancel()
            try:
                await self._image_worker_task
            except asyncio.CancelledError:
                pass
            self._image_worker_task = None

    # -- per-frame analysis (Tier 1 → Tier 2 → Tier 3) -----------------------

    async def _process_image(self, client_id: str, image_bytes: bytes) -> None:
        """Run the image processing pipeline for a received image."""
        coord = self.coord
        async with self._process_lock:
            coord._current_client_id = client_id
            coord._client_registry.set_active(client_id)
            coord._gaming_mode = True
            coord._touch_client(client_id, coord._client_metadata.get(client_id, {}))

            metadata = coord._client_metadata.get(client_id, {})
            metadata["assistant_mode"] = coord._assistant_mode

            game = metadata.get("window_title", "")
            if game:
                coord._current_game = game
                await coord._ensure_state_loaded(game)

            # Tier 1: cheaply measure the frame (scene change, motion).
            perception = await coord._perception.observe(
                client_id, image_bytes, metadata
            )
            coord._last_scene_change = perception.scene_change
            coord._last_frame_motion = perception.measured.get("frame_motion", "")

            # Escalation gate: only spend a Tier 2 (LLM) call on a significant
            # change, or when the heartbeat has elapsed. Otherwise record the
            # measured signals and skip the expensive analysis entirely.
            now = time.monotonic()
            idle = (
                float("inf")
                if coord._last_tier2_ts is None
                else now - coord._last_tier2_ts
            )
            if not coord._perception.should_escalate(perception, idle):
                coord._frames_skipped += 1
                if game and perception.measured:
                    coord._game_state.update(
                        game, perception.measured,
                        source=f"perception:{client_id}",
                    )
                coord._status = "idle"
                _LOGGER.debug(
                    "Tier 2 skipped for %s (scene_change=%.3f, idle=%.0fs)",
                    client_id, perception.scene_change, idle,
                )
                coord._notify_update()
                return

            # Tier 2 escalation — run the LLM analysis.
            coord._last_tier2_ts = now
            coord._status = "analyzing"
            coord._notify_update()

            try:
                start = time.monotonic()
                # Tier 3 feedback: inject the current strategic focus so the
                # tactical tip reasons under the session's higher-level frame.
                strategy_note = coord._strategy.note(game)
                tip = await asyncio.wait_for(
                    coord._image_processor.process(
                        image_bytes, client_id, metadata,
                        measured=perception.measured,
                        strategy_note=strategy_note,
                    ),
                    timeout=coord._analysis_timeout + 5,
                )
                coord._latency = round(time.monotonic() - start, 3)

                # A produced tip counts as a successful round-trip, even if the
                # output gate later suppresses it — the backend is healthy.
                if tip:
                    coord._llm_failure_streak = 0

                # Output-quality gate: reject degenerate output (empty,
                # refusals) and avoid re-announcing a repeat of the last tip.
                verdict = tip_filter.evaluate_tip(tip or "", coord._tip)

                if tip and verdict != "reject":
                    coord._tip = tip
                    coord._tip_count += 1
                    coord._frames_processed += 1
                    coord._last_analysis = (
                        time.strftime("%Y-%m-%dT%H:%M:%S")
                    )
                    coord._recent_tips.append({
                        "tip": tip,
                        "game": coord._current_game,
                        "client_id": client_id,
                    })
                    if len(coord._recent_tips) > 5:
                        coord._recent_tips = coord._recent_tips[-5:]
                    coord._status = "idle"
                    _LOGGER.info("New tip generated: %s", tip[:80])

                    # Track tip for session summary
                    coord._session_tracker.track_tip(tip, coord._current_game)

                    # Tier 3: refresh the session-level strategic focus
                    # (game state is already updated for this frame). When a
                    # refresh is due, optionally upgrade the deterministic
                    # baseline with an LLM reflection in the background (if
                    # enabled) so it never adds latency to the tip path.
                    if (
                        coord._strategy.record_tip(coord._current_game, tip)
                        and coord._strategy.reflection_enabled
                    ):
                        coord.hass.async_create_task(
                            coord._strategy.async_reflect(coord._current_game)
                        )

                    # A repeat of the last tip is surfaced on the sensor but
                    # not re-announced, so the coach doesn't talk over itself
                    # or re-fire automations for the same situation.
                    if verdict == "accept":
                        # Fire event for automations
                        coord._fire_new_tip_event(
                            tip, coord._current_game, client_id
                        )
                        # Auto-announce via TTS if enabled
                        if coord._auto_announce and coord._tts_entity:
                            coord.hass.async_create_task(coord.async_announce(tip))
                    else:  # repeat
                        coord._announces_suppressed += 1
                        _LOGGER.debug("Repeat tip suppressed from announce")

                    # Agent Mode: also produce + publish a controller action.
                    if coord._agent_mode:
                        await self._maybe_publish_agent_action(
                            client_id, image_bytes, coord._current_game
                        )
                else:
                    # Either no tip, or the gate rejected degenerate output.
                    if tip and verdict == "reject":
                        coord._tips_rejected += 1
                        _LOGGER.debug(
                            "Degenerate tip rejected: %s", (tip or "")[:60]
                        )
                    coord._frames_processed += 1
                    coord._status = "idle"

            except (TimeoutError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Image processing timed out after %ds for client %s",
                    coord._analysis_timeout + 5, client_id
                )
                coord._record_error(
                    err
                    if str(err)
                    else TimeoutError(
                        f"timeout after {coord._analysis_timeout + 5}s"
                    )
                )
                coord._status = "error"
            except (OSError, json.JSONDecodeError, ValueError) as err:
                _LOGGER.error("Image processing failed: %s", err)
                coord._record_error(err)
                coord._status = "error"
            finally:
                coord._notify_update()

    # -- Agent Mode action publishing ----------------------------------------

    async def _maybe_publish_agent_action(
        self, client_id: str, image_bytes: bytes, game: str
    ) -> None:
        """Generate one controller action from the frame and publish it.

        Safety-governed: actions are rate limited, repeated failures
        auto-disable Agent Mode (dead-man switch), and every decision is
        recorded for audit. Fully isolated: any failure here must never
        disrupt the tip pipeline.
        """
        coord = self.coord
        now = time.monotonic()
        if coord._agent_governor.rate_limited(now):
            _LOGGER.debug(
                "Agent action rate-limited (<%.1fs), skipping",
                AGENT_ACTION_MIN_INTERVAL,
            )
            return

        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            action = await asyncio.wait_for(
                coord._image_processor.generate_action(
                    image_bytes,
                    game,
                    allowed_buttons=coord._agent_allowed_buttons or None,
                ),
                timeout=coord._analysis_timeout + 5,
            )
        except Exception as err:  # noqa: BLE001 - never break analysis on action errors
            _LOGGER.warning("Agent action generation failed: %s", err)
            if coord._agent_governor.record_error(ts):
                _LOGGER.error(
                    "Agent Mode auto-disabled after %d consecutive failures",
                    coord._agent_governor.max_consecutive_failures,
                )
                coord.set_agent_mode(False)
                self._fire_agent_action_event(client_id, game, "auto_disabled", None)
            else:
                self._fire_agent_action_event(client_id, game, "error", None)
            coord._notify_update()
            return

        if not action:
            coord._agent_governor.record_no_op(ts)
            coord._notify_update()
            return

        await coord.async_publish_action(client_id, action)
        coord._agent_governor.record_published(action, now, ts)
        self._fire_agent_action_event(client_id, game, "published", action)
        coord._notify_update()

    def _fire_agent_action_event(
        self, client_id: str, game: str, status: str, action: dict | None
    ) -> None:
        """Fire an event for each Agent Mode decision (audit / automations)."""
        coord = self.coord
        coord.hass.bus.async_fire(
            EVENT_AGENT_ACTION,
            {
                "client_id": client_id,
                "game": game,
                "status": status,
                "action": action,
                "published": coord._agent_governor.published,
                "failed": coord._agent_governor.failed,
            },
        )
