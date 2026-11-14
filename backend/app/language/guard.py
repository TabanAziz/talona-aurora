"""The facts a translation must not touch: sheet ids, revisions, unit ids, dates, times and numbers.

Tokens are collected from the English text by pattern. A translation passes only when every token appears in it
unchanged, as a whole token, and it names no sheet, revision or unit that the English text does not.
"""
import re
from dataclasses import dataclass

UNITS = r"(?:mm|cm|km|m2|m²|m3|m³|m|kg|kN|MPa|t|l|°C|%|h|hrs|min)"

# Order matters: at one position the first alternative that matches wins, so a datetime is never read as a
# date plus a time, and "300 mm" is never read as the bare number 300.
PATTERNS: list[tuple[str, str]] = [
    ("datetime", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?"),
    ("date", r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4}"),
    ("time", r"\d{1,2}:\d{2}"),
    ("sheet", r"[A-Z]{1,3}-\d{2,4}[A-Z]?"),
    ("revision", r"[Rr]ev\.?\s?[A-Z0-9]{1,2}"),
    ("measure", rf"\d+(?:[.,]\d+)?\s?{UNITS}"),
    ("unit", r"\d{1,2}[A-Z]"),
    ("number", r"\d+(?:[.,]\d+)?"),
]
IDENTIFIERS = {"sheet", "revision", "unit"}

_TOKEN = re.compile(
    r"(?<![\w.:-])(?:" + "|".join(f"(?P<{kind}>{pattern})" for kind, pattern in PATTERNS) + r")(?![\w:])"
)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str


def tokens(text: str) -> list[Token]:
    """The protected tokens of a text, each distinct one once, in order of appearance."""
    found: list[Token] = []
    for match in _TOKEN.finditer(text or ""):
        token = Token(match.lastgroup or "number", match.group(0))
        if token not in found:
            found.append(token)
    return found


def problems(english: str, translation: str) -> list[str]:
    """Why a translation does not keep the facts of the English text; empty when it does."""
    kept = set(tokens(translation))
    issues = [f"{token.kind} {token.text!r} missing or changed" for token in tokens(english) if token not in kept]
    source = {token for token in tokens(english) if token.kind in IDENTIFIERS}
    issues += [
        f"{token.kind} {token.text!r} added"
        for token in kept
        if token.kind in IDENTIFIERS and token not in source
    ]
    return issues
