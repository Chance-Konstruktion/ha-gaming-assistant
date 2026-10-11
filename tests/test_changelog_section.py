"""Tests for tools/changelog_section.py (GitHub release notes from CHANGELOG.md)."""

import importlib.util
import io
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "changelog_section", _ROOT / "tools" / "changelog_section.py"
)
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

CHANGELOG = """# Changelog

## [Unreleased]

### Added

- Something new.

## [261012] - 2026-10-12 — "Chess Bot & Voice"

### Added

- The chess bot.

### Fixed

- A bug.

## [260619] - 2026-06-19

- Older entry.

## [0.1.3]
- Initial public release.

[261012]: https://example.org/compare/v260619...v261012
"""


class TestSection(unittest.TestCase):
    def test_tag_with_v_finds_the_version(self):
        notes = cs.section(CHANGELOG, "v261012")
        self.assertTrue(notes.startswith("**Chess Bot & Voice**"))
        self.assertIn("- The chess bot.", notes)
        self.assertIn("### Fixed", notes)
        self.assertNotIn("Older entry", notes)
        self.assertNotIn("Something new", notes)

    def test_date_only_heading_has_no_title_line(self):
        self.assertEqual(cs.section(CHANGELOG, "260619"), "- Older entry.")

    def test_last_section_drops_link_references(self):
        self.assertEqual(cs.section(CHANGELOG, "0.1.3"), "- Initial public release.")

    def test_unknown_version(self):
        self.assertIsNone(cs.section(CHANGELOG, "v999999"))

    def test_the_real_changelog_has_the_current_release(self):
        text = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        notes = cs.section(text, "v260619")
        self.assertIn("Tiered Cognition", notes)


class TestMain(unittest.TestCase):
    def _run(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cs.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_prints_the_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, "CHANGELOG.md")
            path.write_text(CHANGELOG, encoding="utf-8")
            code, out, _ = self._run("v261012", str(path))
        self.assertEqual(code, 0)
        self.assertIn("The chess bot.", out)

    def test_missing_entry_warns_but_does_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp, "CHANGELOG.md")
            path.write_text(CHANGELOG, encoding="utf-8")
            code, out, err = self._run("v999999", str(path))
        self.assertEqual(code, 0)
        self.assertIn("see CHANGELOG.md", out)
        self.assertIn("warning", err)

    def test_usage_error(self):
        code, _, err = self._run()
        self.assertEqual(code, 2)
        self.assertIn("Usage", err)


if __name__ == "__main__":
    unittest.main()
