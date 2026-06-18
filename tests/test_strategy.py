"""Behavioural tests for the Tier 3 StrategyTier.

Strategy is deterministic here: it reads the trends the GameStateManager
detects across its snapshot window and maps them to a concise strategic
focus, recomputed every few tips. Tests use a real GameStateManager and a
minimal fake coordinator that just exposes ``game_state_manager``.
"""

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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

import custom_components.gaming_assistant.strategy as strategy_mod  # noqa: E402
from custom_components.gaming_assistant.strategy import (  # noqa: E402
    StrategyTier,
)
from custom_components.gaming_assistant.game_state import (  # noqa: E402
    GameStateManager,
)


def _make_tier():
    manager = GameStateManager()
    coord = SimpleNamespace(game_state_manager=manager)
    return StrategyTier(coord), manager


class TestSynthesize(unittest.TestCase):
    def test_declining_health_to_defensive(self):
        note = StrategyTier._synthesize_note(
            ["health declining: 100 → 80 → 60 over 3 frames"]
        )
        self.assertIn("survival", note.lower())

    def test_stable_phase_to_stalled(self):
        note = StrategyTier._synthesize_note(
            ["phase stable at middlegame for 4 frames"]
        )
        self.assertIn("stalled", note.lower())

    def test_momentum_loss_to_change_tactics(self):
        note = StrategyTier._synthesize_note(
            ["momentum stable at losing for 3 frames"]
        )
        self.assertIn("momentum", note.lower())

    def test_no_trends_yields_empty(self):
        self.assertEqual(StrategyTier._synthesize_note([]), "")

    def test_directives_are_capped(self):
        trends = [
            "health declining: 100 → 80 → 60 over 3 frames",
            "phase stable at middlegame for 4 frames",
            "momentum stable at losing for 3 frames",
        ]
        note = StrategyTier._synthesize_note(trends)
        # At most MAX_DIRECTIVES sentences are combined.
        self.assertLessEqual(
            note.count("."), strategy_mod.MAX_DIRECTIVES + 0  # one '.' each
        )


class TestRecordTipFlow(unittest.TestCase):
    def setUp(self):
        self._orig_n = strategy_mod.STRATEGY_EVERY_N_TIPS

    def tearDown(self):
        strategy_mod.STRATEGY_EVERY_N_TIPS = self._orig_n

    def _push_declining_health(self, manager):
        for hp in (100, 80, 60):
            manager.update("Doom", {"health": hp})

    def test_note_updates_after_threshold(self):
        strategy_mod.STRATEGY_EVERY_N_TIPS = 1
        tier, manager = _make_tier()
        self._push_declining_health(manager)
        tier.record_tip("Doom", "some tip")
        self.assertIn("survival", tier.note("Doom").lower())

    def test_note_empty_before_threshold(self):
        strategy_mod.STRATEGY_EVERY_N_TIPS = 5
        tier, manager = _make_tier()
        self._push_declining_health(manager)
        tier.record_tip("Doom", "some tip")  # only 1 < 5
        self.assertEqual(tier.note("Doom"), "")

    def test_stale_note_expires_when_trend_gone(self):
        strategy_mod.STRATEGY_EVERY_N_TIPS = 1
        tier, manager = _make_tier()
        self._push_declining_health(manager)
        tier.record_tip("Doom", "tip")
        self.assertNotEqual(tier.note("Doom"), "")
        # Replace with a trend that maps to no directive (a plain shift),
        # so the next refresh clears the stale note.
        manager.clear("Doom")
        for hp in (50, 70, 50):  # non-monotonic, non-stable -> "shifted"
            manager.update("Doom", {"health": hp})
        tier.record_tip("Doom", "tip")
        self.assertEqual(tier.note("Doom"), "")

    def test_reset_clears_state(self):
        strategy_mod.STRATEGY_EVERY_N_TIPS = 1
        tier, manager = _make_tier()
        self._push_declining_health(manager)
        tier.record_tip("Doom", "tip")
        tier.reset("Doom")
        self.assertEqual(tier.note("Doom"), "")

    def test_empty_game_is_noop(self):
        tier, _ = _make_tier()
        tier.record_tip("", "tip")  # must not raise
        self.assertEqual(tier.note(""), "")

    def test_record_tip_signals_when_due(self):
        strategy_mod.STRATEGY_EVERY_N_TIPS = 2
        tier, _ = _make_tier()
        self.assertFalse(tier.record_tip("Doom", "a"))  # 1 < 2
        self.assertTrue(tier.record_tip("Doom", "b"))   # 2 >= 2 -> due


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeHistory:
    def __init__(self, tips):
        self._tips = tips

    async def get_recent(self, game, count):
        return [{"tip": t} for t in self._tips]


def _make_llm_tier(llm_text="Hold the high ground and conserve resources.",
                   history_tips=("dodge", "heal")):
    manager = GameStateManager()
    image_processor = SimpleNamespace(
        _call_ollama_text=AsyncMock(return_value=llm_text)
    )
    notified = []
    coord = SimpleNamespace(
        game_state_manager=manager,
        history_manager=_FakeHistory(list(history_tips)),
        image_processor=image_processor,
        config={"model": "qwen2.5vl"},
        _language="en",
        _notify_update=lambda: notified.append(True),
    )
    return StrategyTier(coord), manager, image_processor, notified


class TestLLMReflection(unittest.TestCase):
    def test_reflection_sets_llm_note(self):
        tier, manager, proc, notified = _make_llm_tier(
            llm_text="Play aggressively and push the objective."
        )
        note = _run(tier.async_reflect("Doom"))
        self.assertEqual(note, "Play aggressively and push the objective.")
        self.assertEqual(tier.note("Doom"), note)
        self.assertTrue(notified)  # _notify_update called
        self.assertTrue(proc._call_ollama_text.await_count >= 1)

    def test_reflection_strips_label_and_truncates(self):
        tier, *_ = _make_llm_tier(
            llm_text="Strategic focus: Keep your shield up.\nExtra line."
        )
        note = _run(tier.async_reflect("Doom"))
        self.assertEqual(note, "Keep your shield up.")

    def test_reflection_falls_back_to_deterministic_when_empty(self):
        tier, manager, _, _ = _make_llm_tier(llm_text="")
        for hp in (100, 80, 60):
            manager.update("Doom", {"health": hp})
        note = _run(tier.async_reflect("Doom"))
        self.assertIn("survival", note.lower())  # deterministic fallback

    def test_reflection_survives_backend_error(self):
        tier, manager, proc, _ = _make_llm_tier()
        proc._call_ollama_text = AsyncMock(side_effect=RuntimeError("no llm"))
        for hp in (100, 80, 60):
            manager.update("Doom", {"health": hp})
        note = _run(tier.async_reflect("Doom"))  # must not raise
        self.assertIn("survival", note.lower())  # fell back to deterministic

    def test_reflection_empty_game_is_noop(self):
        tier, *_ = _make_llm_tier()
        self.assertEqual(_run(tier.async_reflect("")), "")


if __name__ == "__main__":
    unittest.main()
