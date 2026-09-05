"""Unit tests for the output-quality gate (chess-free, no HA needed)."""

import sys
import unittest
from unittest.mock import MagicMock

# Importing via the package runs __init__.py (imports HA). Stub it; tip_filter
# itself has no HA dependency.
for _mod in (
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
):
    sys.modules.setdefault(_mod, MagicMock())

from custom_components.gaming_assistant import tip_filter as tf  # noqa: E402


class TestIsDegenerate(unittest.TestCase):
    def test_empty_and_whitespace(self):
        self.assertTrue(tf.is_degenerate(""))
        self.assertTrue(tf.is_degenerate("   "))

    def test_too_short(self):
        self.assertTrue(tf.is_degenerate("go"))

    def test_refusals(self):
        self.assertTrue(tf.is_degenerate("I can't see the image you provided."))
        self.assertTrue(tf.is_degenerate("As an AI, I cannot help with that."))
        self.assertTrue(tf.is_degenerate("There is no image to analyse."))

    def test_good_tip_is_not_degenerate(self):
        self.assertFalse(
            tf.is_degenerate("Flank the sniper from the left and use cover.")
        )


class TestIsRepeat(unittest.TestCase):
    def test_identical(self):
        self.assertTrue(tf.is_repeat("Use cover now.", "Use cover now."))

    def test_near_identical(self):
        self.assertTrue(
            tf.is_repeat("Use cover now!", "Use cover now.")
        )

    def test_different(self):
        self.assertFalse(
            tf.is_repeat("Push the objective.", "Retreat and heal up.")
        )

    def test_no_previous(self):
        self.assertFalse(tf.is_repeat("Use cover.", ""))


class TestEvaluateTip(unittest.TestCase):
    def test_reject(self):
        self.assertEqual(tf.evaluate_tip("", "prev"), "reject")
        self.assertEqual(tf.evaluate_tip("I can't see the image.", "prev"), "reject")

    def test_repeat(self):
        self.assertEqual(
            tf.evaluate_tip("Use cover now.", "Use cover now."), "repeat"
        )

    def test_accept(self):
        self.assertEqual(
            tf.evaluate_tip("Save your ultimate for the boss.", "Use cover."),
            "accept",
        )


if __name__ == "__main__":
    unittest.main()
