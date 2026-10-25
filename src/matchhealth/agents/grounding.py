"""Grounding guard: every number an agent writes must come from its facts.

The prompts tell the Analyst, Narrator and Personaliser to cite only the
numbers they were given; this checks that they did, in plain code, before
anything reaches a viewer. A number that isn't in the facts (in any of the
roundings a writer might use) is "ungrounded": the text is replaced by the
template built from the same facts, and the rejection is recorded.

Only 0-3 and match-time words ("in 5 minutes", "90 minutes", "100%") are
always allowed; every other number has to be in the facts.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?")
# Kept deliberately small: "his 7th goal" is exactly the kind of number that
# must come from the facts, so only 0-3 and match-time words pass unchecked.
ALWAYS_OK = {0.0, 1.0, 2.0, 3.0, 5.0, 15.0, 45.0, 60.0, 90.0, 100.0}


def _canon(value: float) -> str:
    return f"{value:.2f}"


def allowed_numbers(*sources) -> set[str]:
    """Every number in the facts, as it might be written: exact, rounded to
    0/1/2 decimals, or truncated. Strings contribute their digits too, so a
    clock like "33:26" allows 33 and 26."""
    out: set[str] = set()

    def walk(v) -> None:
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            x = float(v)
            for r in (0, 1, 2):
                out.add(_canon(round(x, r)))
            out.add(_canon(float(int(x))))
        elif isinstance(v, str):
            for n in _NUM.findall(v):
                walk(float(n.replace(",", ".")))
        elif isinstance(v, dict):
            for item in v.values():
                walk(item)
        elif isinstance(v, (list, tuple, set)):
            for item in v:
                walk(item)

    for source in sources:
        walk(source)
    return out


def ungrounded(text: str, allowed: set[str]) -> list[str]:
    """Numbers in `text` that appear nowhere in the facts."""
    bad = []
    for n in _NUM.findall(text or ""):
        x = float(n.replace(",", "."))  # 1,07 in French, Portuguese, German
        if x in ALWAYS_OK or _canon(x) in allowed:
            continue
        bad.append(n)
    return bad
