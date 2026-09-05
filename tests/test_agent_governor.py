"""Unit tests for the Agent Mode safety governor.

AgentActionGovernor is pure Python with no Home Assistant dependency, so it
can be imported and exercised directly — these are real behavioural tests of
the rate-limiting, failure auto-disable, and audit-counter logic.
"""

import importlib.util
import pathlib
import unittest

# Load agent_governor.py directly by path so we bypass the package __init__
# (which imports Home Assistant). The module itself is pure Python, so this
# keeps the test independent of import order and HA stubs.
_GOV_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "gaming_assistant"
    / "agent_governor.py"
)
_spec = importlib.util.spec_from_file_location("agent_governor_standalone", _GOV_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
AgentActionGovernor = _mod.AgentActionGovernor


class TestRateLimiting(unittest.TestCase):
    def test_first_action_is_never_rate_limited(self):
        gov = AgentActionGovernor(min_interval=1.0, max_consecutive_failures=5)
        self.assertFalse(gov.rate_limited(0.0))
        self.assertFalse(gov.rate_limited(123456.0))

    def test_rate_limited_within_interval(self):
        gov = AgentActionGovernor(min_interval=1.0, max_consecutive_failures=5)
        gov.record_published({"action": "no_op"}, now=10.0, ts_iso="t")
        self.assertTrue(gov.rate_limited(10.0))
        self.assertTrue(gov.rate_limited(10.99))
        # Exactly at the interval boundary is allowed.
        self.assertFalse(gov.rate_limited(11.0))
        self.assertFalse(gov.rate_limited(50.0))

    def test_zero_interval_never_limits(self):
        gov = AgentActionGovernor(min_interval=0.0, max_consecutive_failures=5)
        gov.record_published({"action": "x"}, now=10.0, ts_iso="t")
        self.assertFalse(gov.rate_limited(10.0))


class TestFailureAutoDisable(unittest.TestCase):
    def test_threshold_triggers_after_n_consecutive(self):
        gov = AgentActionGovernor(min_interval=1.0, max_consecutive_failures=3)
        self.assertFalse(gov.record_error("t"))  # 1
        self.assertFalse(gov.record_error("t"))  # 2
        self.assertTrue(gov.record_error("t"))   # 3 -> auto-disable
        self.assertEqual(gov.failed, 3)
        self.assertEqual(gov.last_status, "error")

    def test_published_resets_failure_streak(self):
        gov = AgentActionGovernor(min_interval=1.0, max_consecutive_failures=3)
        gov.record_error("t")
        gov.record_error("t")
        gov.record_published({"action": "button", "button": "A"}, now=5.0, ts_iso="t")
        self.assertEqual(gov.consecutive_failures, 0)
        self.assertEqual(gov.published, 1)
        self.assertEqual(gov.last_status, "published")
        self.assertEqual(gov.last_action, {"action": "button", "button": "A"})
        # A subsequent single failure must not immediately re-trigger.
        self.assertFalse(gov.record_error("t"))

    def test_no_op_resets_failure_streak(self):
        gov = AgentActionGovernor(min_interval=1.0, max_consecutive_failures=3)
        gov.record_error("t")
        gov.record_error("t")
        gov.record_no_op("t")
        self.assertEqual(gov.consecutive_failures, 0)
        self.assertEqual(gov.last_status, "no_op")

    def test_reset_failures(self):
        gov = AgentActionGovernor(min_interval=1.0, max_consecutive_failures=3)
        gov.record_error("t")
        gov.record_error("t")
        gov.reset_failures()
        self.assertEqual(gov.consecutive_failures, 0)
        # failed total is a lifetime counter and is NOT reset.
        self.assertEqual(gov.failed, 2)

    def test_min_threshold_is_at_least_one(self):
        gov = AgentActionGovernor(min_interval=1.0, max_consecutive_failures=0)
        # Clamped to >=1, so a single error auto-disables.
        self.assertTrue(gov.record_error("t"))


class TestSnapshot(unittest.TestCase):
    def test_snapshot_shape(self):
        gov = AgentActionGovernor(min_interval=1.0, max_consecutive_failures=5)
        gov.record_published({"action": "stick", "stick": "left"}, now=1.0, ts_iso="ts1")
        snap = gov.snapshot()
        self.assertEqual(snap["published"], 1)
        self.assertEqual(snap["failed"], 0)
        self.assertEqual(snap["last_status"], "published")
        self.assertEqual(snap["last_action"], {"action": "stick", "stick": "left"})
        self.assertEqual(snap["last_timestamp"], "ts1")


if __name__ == "__main__":
    unittest.main()
