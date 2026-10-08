"""Pytest configuration shared across the whole suite.

The only thing configured here is a guard against *silent* skips in CI.

Several test modules self-skip when an optional dependency is absent (the HDMI
capture bridge needs ``numpy``; the chess-grounding tests need ``python-chess``).
That is the right behaviour for a developer who has not installed the optional
extras — but in CI every test dependency *is* installed (see
``requirements-test.txt``), so a skip there does not mean "optional": it means a
dependency silently went missing and an entire module (capture bridge, chess
grounding, ...) quietly stopped being exercised. That is exactly the blind spot
we want CI to shout about rather than swallow.

So when ``STRICT_NO_SKIP`` is set (CI sets it to ``1``), any skipped test fails
the run and the offending tests are listed. Locally the variable is unset and
skips behave normally.
"""

from __future__ import annotations

import os


def pytest_sessionfinish(session, exitstatus):
    if not os.environ.get("STRICT_NO_SKIP"):
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = reporter.stats.get("skipped", []) if reporter else []
    if not skipped:
        return

    print(
        "\nSTRICT_NO_SKIP: tests were skipped in CI — a test dependency is "
        "missing (see requirements-test.txt). Skipped tests:"
    )
    for report in skipped:
        reason = report.longrepr
        if isinstance(reason, tuple) and len(reason) == 3:
            reason = reason[2]  # (path, lineno, message) -> message
        print(f"  - {report.nodeid}  [{reason}]")

    # A clean exit (0) or "tests failed" (1) becomes "skips present" (1).
    if session.exitstatus == 0:
        session.exitstatus = 1
