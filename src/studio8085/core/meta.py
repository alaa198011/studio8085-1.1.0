"""Optional program metadata written as comments at the top of a source file::

    ; @title: Bubble sort
    ; @topic: Loops and memory addressing
    ; @validation: T

Keys are free-form; the interface shows them in the Explain panel.
"""

from __future__ import annotations

import re

_META = re.compile(r"^\s*;\s*@([A-Za-z_][\w-]*)\s*:\s*(.*?)\s*$")

KNOWN_KEYS = ("title", "id", "chapter", "section", "topic", "level", "validation", "related")


def parse_metadata(lines) -> dict[str, str]:
    """Read ``; @key: value`` lines from the leading comment block."""
    meta: dict[str, str] = {}
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if not s.startswith(";"):
            break
        m = _META.match(raw)
        if m:
            meta[m.group(1).lower()] = m.group(2)
    return meta


# The T / M / H labels follow the book's front-matter definitions (no label is ever inherited).
VALIDATION_LABELS = {
    "T": "Tool-tested: assembled or run in the stated simulator at the stated version",
    "M": "Manually validated: traced, calculated or checked independently by the author",
    "H": "Hardware-validated: run on a specified physical system or circuit simulator, with a schematic and a measurement",
}
VALIDATION_LIMITS = {
    "T": "Does not prove real timing, electrical behaviour or true interrupt behaviour.",
    "M": "Does not prove that any code runs; pair with T where code exists.",
    "H": "Does not prove anything outside the documented setup.",
}
VALIDATION_RULE = "No label is inherited: each example earns its own."


def describe_validation(value: str, with_limits: bool = False) -> list[str]:
    """'T+M' -> the description of each letter (optionally with what it does not prove)."""
    out = []
    for ch in re.split(r"[+,\s/]+", value.upper()):
        if ch in VALIDATION_LABELS:
            text = f"{ch} = {VALIDATION_LABELS[ch]}"
            if with_limits:
                text += f". {VALIDATION_LIMITS[ch]}"
            out.append(text)
    return out
