"""Spoken crew briefings: text that is heard right, and a clip of it.

`script(briefing)` rewrites one briefing for the ear: sheet ids, revisions, unit ids and times are spelled so a
speech service says them the way a person would, while the written message keeps the exact ids. `speak(text,
language)` turns text into an audio file under `DATA_DIR/files/briefings` and returns its URL, or None.

The clip is cached by a hash of text and language, so the same briefing never costs a second call. With the voice
API mocked, a committed sample clip is used instead of the network. Any failure returns None and the briefing goes
out as text, which is why this module never raises.
"""
from .clips import DAILY_CAP_DEFAULT, clip_url, speak
from .script import limit, script

__all__ = ["DAILY_CAP_DEFAULT", "clip_url", "limit", "script", "speak"]
