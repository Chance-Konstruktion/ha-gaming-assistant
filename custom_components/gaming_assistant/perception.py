"""Tier 1 — Reflex / Perception layer for the Gaming Assistant.

This is the cheap, deterministic, no-LLM layer of the tiered cognition
stack. It runs on *every* incoming frame before the expensive Tier 2
(vision-LLM) call and turns raw pixels into **measured** signals:

* a normalised scene-change magnitude (how much moved since the last
  frame for this client), derived from the perceptual hash, and
* a coarse motion class (``static`` / ``low`` / ``high``).

Why this matters: historically the integration derived its structured
game state by *scraping the LLM's prose tip back out with regexes*
(``game_state.extract_observations_from_tip``). That is backwards — the
"perception" was downstream of, and dependent on, the model's wording.
Tier 1 inverts the flow: it measures first, hands the measurements to
Tier 2 as **input**, and exposes an escalation hint so the tactical tier
can fire on *change* instead of a dumb fixed interval.

This is a collaborator of :class:`GamingAssistantCoordinator`. It owns the
per-client perceptual-hash memory and reaches back through the coordinator
only for the event loop (to keep the Pillow decode off the event loop).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .image_processor import ImageProcessor

if TYPE_CHECKING:
    from .coordinator import GamingAssistantCoordinator

_LOGGER = logging.getLogger(__name__)

# Perceptual hash is an 8x8 average hash -> 64 bits. Scene change is the
# fraction of differing bits, so it lives in [0.0, 1.0].
PHASH_BITS = 64

# A frame whose scene-change magnitude meets this threshold is considered
# a "significant" change worth a fresh Tier 2 analysis.
SCENE_CHANGE_SIGNIFICANT = 0.18

# Coarse motion classification thresholds (fraction of changed bits).
MOTION_STATIC_BELOW = 0.03
MOTION_HIGH_ABOVE = 0.18


@dataclass(frozen=True)
class PerceptionResult:
    """Outcome of a single Tier 1 observation."""

    scene_change: float = 0.0
    significant: bool = True
    measured: dict[str, Any] = field(default_factory=dict)


class PerceptionTier:
    """Tier 1: cheap per-frame perception that feeds Tier 2.

    Pure measurement — does not call the LLM and does not mutate game
    state itself. It returns measured observations; the coordinator hands
    them to the image processor so they become part of a single state
    snapshot per frame (instead of a competing one).
    """

    def __init__(self, coordinator: GamingAssistantCoordinator) -> None:
        self.coord = coordinator
        # client_id -> last perceptual hash, so scene change is per source.
        self._last_phash: dict[str, int] = {}

    async def observe(
        self,
        client_id: str,
        image_bytes: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> PerceptionResult:
        """Measure a frame and return deterministic perception signals."""
        if not image_bytes:
            return PerceptionResult(scene_change=0.0, significant=False)

        # pHash decodes the image with Pillow; keep it off the event loop.
        phash = await self.coord.hass.async_add_executor_job(
            ImageProcessor._compute_phash, image_bytes
        )

        previous = self._last_phash.get(client_id)
        self._last_phash[client_id] = phash

        if previous is None:
            # First frame for this client — nothing to diff against, so it
            # is by definition worth analysing.
            measured = self._build_measured(1.0)
            return PerceptionResult(
                scene_change=1.0, significant=True, measured=measured
            )

        distance = ImageProcessor._hamming_distance(previous, phash)
        scene_change = round(distance / PHASH_BITS, 3)
        significant = scene_change >= SCENE_CHANGE_SIGNIFICANT

        measured = self._build_measured(scene_change)
        _LOGGER.debug(
            "Perception %s: scene_change=%.3f motion=%s significant=%s",
            client_id, scene_change, measured["frame_motion"], significant,
        )
        return PerceptionResult(
            scene_change=scene_change,
            significant=significant,
            measured=measured,
        )

    @staticmethod
    def _build_measured(scene_change: float) -> dict[str, Any]:
        """Turn a scene-change magnitude into measured observations."""
        if scene_change <= MOTION_STATIC_BELOW:
            motion = "static"
        elif scene_change >= MOTION_HIGH_ABOVE:
            motion = "high"
        else:
            motion = "low"
        return {"scene_change": scene_change, "frame_motion": motion}

    def reset(self, client_id: str | None = None) -> None:
        """Forget perceptual-hash memory for one client or all clients."""
        if client_id is None:
            self._last_phash.clear()
        else:
            self._last_phash.pop(client_id, None)
