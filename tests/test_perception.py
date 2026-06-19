"""Behavioural tests for the Tier 1 PerceptionTier.

Perception is pure measurement: it diffs each frame's perceptual hash
against the previous one for the same client and emits a normalised
scene-change magnitude plus a coarse motion class. A minimal fake hass
provides the executor the tier uses to keep the Pillow decode off the
event loop.
"""

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

_HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.mqtt",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.event",
]
for _mod in _HA_MODULES:
    sys.modules.setdefault(_mod, MagicMock())

from custom_components.gaming_assistant.perception import (  # noqa: E402
    PerceptionResult,
    PerceptionTier,
    SCENE_CHANGE_SIGNIFICANT,
    TIER2_HEARTBEAT_SECONDS,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _make_tier():
    coord = SimpleNamespace(hass=_FakeHass())
    return PerceptionTier(coord)


class TestPerceptionTier(unittest.TestCase):
    def test_first_frame_is_significant(self):
        tier = _make_tier()
        result = _run(tier.observe("rig1", b"frame-A", {}))
        self.assertEqual(result.scene_change, 1.0)
        self.assertTrue(result.significant)
        self.assertIn("scene_change", result.measured)
        self.assertIn("frame_motion", result.measured)

    def test_identical_frame_has_no_change(self):
        tier = _make_tier()
        _run(tier.observe("rig1", b"frame-A", {}))
        result = _run(tier.observe("rig1", b"frame-A", {}))
        self.assertEqual(result.scene_change, 0.0)
        self.assertFalse(result.significant)
        self.assertEqual(result.measured["frame_motion"], "static")

    def test_different_frame_registers_change(self):
        tier = _make_tier()
        _run(tier.observe("rig1", b"frame-A", {}))
        result = _run(tier.observe("rig1", b"a-totally-different-frame", {}))
        self.assertGreater(result.scene_change, 0.0)

    def test_empty_bytes_not_significant(self):
        tier = _make_tier()
        result = _run(tier.observe("rig1", b"", {}))
        self.assertEqual(result.scene_change, 0.0)
        self.assertFalse(result.significant)
        self.assertEqual(result.measured, {})

    def test_per_client_memory_is_isolated(self):
        tier = _make_tier()
        _run(tier.observe("rig1", b"frame-A", {}))
        # A first frame for a *different* client is still significant.
        result = _run(tier.observe("rig2", b"frame-A", {}))
        self.assertEqual(result.scene_change, 1.0)
        self.assertTrue(result.significant)

    def test_reset_forgets_client(self):
        tier = _make_tier()
        _run(tier.observe("rig1", b"frame-A", {}))
        tier.reset("rig1")
        # After reset the next frame is treated as the first one again.
        result = _run(tier.observe("rig1", b"frame-A", {}))
        self.assertEqual(result.scene_change, 1.0)

    def test_significant_threshold_constant_in_range(self):
        self.assertGreater(SCENE_CHANGE_SIGNIFICANT, 0.0)
        self.assertLess(SCENE_CHANGE_SIGNIFICANT, 1.0)


class TestEscalationPolicy(unittest.TestCase):
    def test_significant_frame_escalates(self):
        result = PerceptionResult(scene_change=0.5, significant=True)
        self.assertTrue(PerceptionTier.should_escalate(result, idle_seconds=0.0))

    def test_static_frame_does_not_escalate(self):
        result = PerceptionResult(scene_change=0.0, significant=False)
        self.assertFalse(PerceptionTier.should_escalate(result, idle_seconds=1.0))

    def test_heartbeat_forces_escalation_when_idle(self):
        result = PerceptionResult(scene_change=0.0, significant=False)
        self.assertTrue(
            PerceptionTier.should_escalate(
                result, idle_seconds=TIER2_HEARTBEAT_SECONDS + 1
            )
        )


if __name__ == "__main__":
    unittest.main()
