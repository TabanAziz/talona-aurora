"""The spoken form of a crew briefing: the same facts, spelled the way a person says them out loud.

The written briefing is built for the record and keeps exact ids (A-201, Rev C, 2A, 14:00). Read aloud by a
speech service, those come out wrong, so this rewrites them for the ear and keeps the result under 60 words. It
never drops a whole sentence to fit: a briefing too long for 60 words loses its last sentences, not half of one.
"""
import re

from app.core import models as m

MAX_WORDS = 60
SHEET = re.compile(r"\b([A-Z]{1,2})-(\d{3})\b")
REVISION = re.compile(r"\bRev\.?\s*([A-Z])\b", re.IGNORECASE)
UNIT = re.compile(r"(?<![\w.])(\d)([A-H])(?=[\s,.;:!?)]|$)")
TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")
SOURCE_IDS = re.compile(r"\s*\[[^\]]*\]")
SITE_TIME = re.compile(r"\s*\(site time\)", re.IGNORECASE)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
SPOKEN_UNIT = re.compile(r"(?:in\s+)?unit\s+(\d)\s+([A-H])", re.IGNORECASE)


def _digits(value: str) -> str:
    return " ".join(value)


def _sheet(match: re.Match) -> str:
    return f"{match.group(1)} {_digits(match.group(2))}"


def _unit(match: re.Match) -> str:
    return f"unit {match.group(1)} {match.group(2)}"


def _time(match: re.Match) -> str:
    hour, minute = int(match.group(1)), int(match.group(2))
    spoken = hour % 12 or 12
    period = "in the morning" if hour < 12 else "in the afternoon" if hour < 18 else "in the evening"
    if minute == 0:
        return f"{spoken} o'clock {period}"
    if minute < 10:
        return f"{spoken} oh {minute} {period}"
    return f"{spoken} {minute} {period}"


def _once(sentence: str) -> str:
    """Name a unit once per sentence: "unit 3 B at 7 in unit 3 B" is one unit too many for the ear."""
    seen: set[str] = set()

    def keep(match: re.Match) -> str:
        key = f"{match.group(1)} {match.group(2)}"
        if key in seen:
            return ""
        seen.add(key)
        return f"unit {key}"

    cleaned = SPOKEN_UNIT.sub(keep, sentence)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    return cleaned


def _text(briefing: m.OutboundMessage | str) -> str:
    return briefing if isinstance(briefing, str) else (getattr(briefing, "text", "") or "")


def limit(text: str) -> str:
    """The 60-word rule on its own, for text that is already in spoken form (a translation of the script)."""
    kept: list[str] = []
    used = 0
    for part in (piece.strip() for piece in SENTENCE_END.split(text.strip())):
        sentence = part.strip(" .;,:")
        if not sentence:
            continue
        words = sentence.split()
        if used + len(words) > MAX_WORDS:
            break
        kept.append(sentence + ".")
        used += len(words)
    return " ".join(kept)


def script(briefing: m.OutboundMessage | str) -> str:
    """The briefing as a person would say it, at most 60 words. Empty text gives an empty script."""
    text = SITE_TIME.sub("", SOURCE_IDS.sub("", _text(briefing)))
    text = SHEET.sub(_sheet, text)
    text = REVISION.sub(lambda match: f"revision {match.group(1).upper()}", text)
    text = TIME.sub(_time, text)
    text = UNIT.sub(_unit, text)
    text = re.sub(r"\s+", " ", text.replace("\n", ". ")).strip(" .;,")
    text = re.sub(r"\.{2,}", ".", text)
    if not text:
        return ""
    spoken = []
    for part in (piece.strip() for piece in SENTENCE_END.split(text)):
        sentence = _once(part).strip(" .;,:")
        if sentence:
            spoken.append(sentence)
    return limit(". ".join(spoken))
