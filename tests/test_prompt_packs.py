"""Validation tests for all prompt pack JSON files."""

import json
import unittest
from pathlib import Path


PACK_DIR = Path(__file__).parent.parent / "custom_components" / "gaming_assistant" / "prompt_packs"

REQUIRED_FIELDS = {"id", "name", "keywords", "system_prompt"}
OPTIONAL_FIELDS = {"spoiler_defaults", "additional_context", "state_schema"}
VALID_SPOILER_CATEGORIES = {"story", "items", "enemies", "bosses", "locations", "lore", "mechanics"}
VALID_SPOILER_LEVELS = {"none", "low", "medium", "high"}


class TestPromptPackValidation(unittest.TestCase):
    """Validate all prompt pack JSON files have correct structure."""

    def _get_pack_files(self) -> list[Path]:
        """Return all non-template pack files."""
        return [
            f for f in PACK_DIR.glob("*.json")
            if not f.name.startswith("_")
        ]

    def test_packs_directory_exists(self):
        self.assertTrue(PACK_DIR.exists(), f"Pack directory not found: {PACK_DIR}")

    def test_at_least_20_packs(self):
        """We should have at least 20 game packs now."""
        packs = self._get_pack_files()
        self.assertGreaterEqual(len(packs), 20, f"Only {len(packs)} packs found")

    def test_all_packs_valid_json(self):
        for path in self._get_pack_files():
            with self.subTest(pack=path.name):
                text = path.read_text(encoding="utf-8")
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    self.fail(f"{path.name} is invalid JSON: {e}")
                self.assertIsInstance(data, dict, f"{path.name} root is not a dict")

    def test_all_packs_have_required_fields(self):
        for path in self._get_pack_files():
            with self.subTest(pack=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                for field in REQUIRED_FIELDS:
                    self.assertIn(field, data, f"{path.name} missing '{field}'")

    def test_keywords_are_lists(self):
        for path in self._get_pack_files():
            with self.subTest(pack=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                kw = data.get("keywords", [])
                self.assertIsInstance(kw, list, f"{path.name} keywords not a list")
                self.assertGreater(len(kw), 0, f"{path.name} has no keywords")

    def test_system_prompt_not_empty(self):
        for path in self._get_pack_files():
            with self.subTest(pack=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                prompt = data.get("system_prompt", "")
                self.assertGreater(len(prompt), 20, f"{path.name} system_prompt too short")

    def test_spoiler_defaults_valid(self):
        for path in self._get_pack_files():
            with self.subTest(pack=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                spoilers = data.get("spoiler_defaults", {})
                if spoilers:
                    for cat, level in spoilers.items():
                        self.assertIn(
                            cat, VALID_SPOILER_CATEGORIES,
                            f"{path.name} invalid spoiler category: {cat}",
                        )
                        self.assertIn(
                            level, VALID_SPOILER_LEVELS,
                            f"{path.name} invalid spoiler level for {cat}: {level}",
                        )

    def test_unique_ids(self):
        ids = []
        for path in self._get_pack_files():
            data = json.loads(path.read_text(encoding="utf-8"))
            ids.append(data.get("id", ""))
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate pack IDs found: {ids}")

    def test_no_overlapping_keywords(self):
        """Keywords should be reasonably unique across packs."""
        keyword_map: dict[str, str] = {}
        conflicts = []
        for path in self._get_pack_files():
            data = json.loads(path.read_text(encoding="utf-8"))
            pack_id = data.get("id", path.stem)
            for kw in data.get("keywords", []):
                kw_lower = kw.lower()
                if kw_lower in keyword_map and keyword_map[kw_lower] != pack_id:
                    conflicts.append(
                        f"'{kw}' in both {keyword_map[kw_lower]} and {pack_id}"
                    )
                keyword_map[kw_lower] = pack_id
        # Allow some overlap (e.g. 'zelda' could be in multiple Zelda games)
        # but flag excessive conflicts
        self.assertLessEqual(
            len(conflicts), 5,
            f"Too many keyword conflicts: {conflicts}",
        )


if __name__ == "__main__":
    unittest.main()
