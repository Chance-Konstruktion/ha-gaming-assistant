"""Output-quality gate for tips (Tier 2) — runs in HA, pure-Python.

The input pipeline already suppresses *similar frames* (dedup + the
state-similarity LLM cache). This is the complementary gate on the *text the
model produced*: it rejects degenerate output (empty, refusals, "I can't see
the image") before it is ever announced, and flags a tip that merely repeats
the last one so we can keep it on the sensor without talking over ourselves.

Cheap and deterministic: a few substring checks plus difflib similarity. No
LLM, no dependency.
"""
from __future__ import annotations

from difflib import SequenceMatcher

# Minimum useful tip length (after stripping). Anything shorter is noise
# (e.g. "", ".", "ok", "n/a"). Kept small so terse but valid coaching like
# "Run!" or "Reload!" still passes — real refusals are caught by markers below.
MIN_TIP_LENGTH = 4

# difflib ratio at/above which a new tip is considered a repeat of the last.
REPEAT_RATIO = 0.92

# Phrases that signal the model refused or couldn't use the frame. Matched
# case-insensitively as substrings — kept short and high-precision.
_REFUSAL_MARKERS = (
    "i can't see",
    "i cannot see",
    "i can not see",
    "unable to see",
    "can't see the image",
    "cannot see the image",
    "no image",
    "there is no image",
    "i'm unable to",
    "i am unable to",
    "as an ai",
    "i cannot assist",
    "i can't assist",
    "i cannot help with",
)


def is_degenerate(tip: str) -> bool:
    """Whether a tip is empty, too short, or a refusal/non-answer."""
    if not tip:
        return True
    text = tip.strip()
    if len(text) < MIN_TIP_LENGTH:
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in _REFUSAL_MARKERS)


def is_repeat(tip: str, last_tip: str, threshold: float = REPEAT_RATIO) -> bool:
    """Whether ``tip`` is essentially the same as the last announced tip."""
    if not last_tip or not tip:
        return False
    a = tip.strip().lower()
    b = last_tip.strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def evaluate_tip(tip: str, last_tip: str) -> str:
    """Classify a freshly generated tip.

    Returns one of:
      * ``"reject"`` — degenerate; do not surface or announce it.
      * ``"repeat"`` — essentially the previous tip; surface but don't re-announce.
      * ``"accept"`` — a fresh, useful tip.
    """
    if is_degenerate(tip):
        return "reject"
    if is_repeat(tip, last_tip):
        return "repeat"
    return "accept"
