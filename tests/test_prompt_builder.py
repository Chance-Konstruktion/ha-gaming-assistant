"""Tests for prompt builder ask-mode behavior."""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "gaming_assistant" / "prompt_builder.py"
SPEC = importlib.util.spec_from_file_location("prompt_builder_module", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)
PromptBuilder = MOD.PromptBuilder


class TestPromptBuilder(unittest.TestCase):
    def test_build_tip_mode_contains_tip_instruction(self):
        prompt = PromptBuilder.build(game="Elden Ring", client_type="pc")
        self.assertIn("Give exactly ONE short, specific, actionable tip", prompt)
        self.assertNotIn("User question:", prompt)

    def test_build_ask_mode_contains_question_instruction(self):
        prompt = PromptBuilder.build(
            game="Minecraft",
            client_type="android",
            user_question="How do I find diamonds quickly?",
        )
        self.assertIn("User question: How do I find diamonds quickly?", prompt)
        self.assertIn("Answer the user question directly and briefly", prompt)
        self.assertNotIn("Give exactly ONE short, specific, actionable tip", prompt)


if __name__ == "__main__":
    unittest.main()
