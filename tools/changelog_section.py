#!/usr/bin/env python3
"""Print the CHANGELOG.md section of one release, for the GitHub release notes.

The release workflow (.github/workflows/release.yml) runs this on a tag push,
so the notes on GitHub are what CHANGELOG.md says about that version instead
of a list of GitHub pull requests (development happens on GitLab, so there are
none).

Usage:
    python tools/changelog_section.py v261012 [CHANGELOG.md]

A leading "v" is ignored: the tag v261012 matches the heading
"## [261012] - 2026-10-12 — ...". The heading's title, if any, becomes the
first line. Without a matching section the script prints a short pointer to
CHANGELOG.md, warns on stderr and still exits 0: a missing entry must not stop
the release itself.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HEADING = re.compile(r"^## \[(?P<version>[^\]]+)\](?P<rest>.*)$", re.MULTILINE)
# Link reference definitions at the end of a Keep-a-Changelog file.
_LINK_REFS = re.compile(r"\n\[[^\]]+\]: \S+\s*$")


def section(text: str, version: str) -> str | None:
    """The notes for *version* (with or without a leading "v"), or None."""
    version = version[1:] if version.startswith("v") else version
    headings = list(_HEADING.finditer(text))
    for i, heading in enumerate(headings):
        if heading.group("version") != version:
            continue
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[heading.end():end]
        while _LINK_REFS.search(body):
            body = _LINK_REFS.sub("", body)
        body = body.strip()
        title = heading.group("rest").strip(" -—–").strip()
        # "2026-10-12 — "Title"" -> "Title"; a bare date says nothing new.
        title = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[—–-]?\s*", "", title).strip().strip('"')
        return f"**{title}**\n\n{body}" if title else body
    return None


def main(argv: list[str]) -> int:
    if not argv or len(argv) > 2:
        print(__doc__, file=sys.stderr)
        return 2
    version = argv[0]
    path = Path(argv[1] if len(argv) > 1 else "CHANGELOG.md")
    notes = section(path.read_text(encoding="utf-8"), version)
    if notes is None:
        print(f"warning: no section for {version} in {path}", file=sys.stderr)
        notes = f"No CHANGELOG entry for {version}; see CHANGELOG.md."
    print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
