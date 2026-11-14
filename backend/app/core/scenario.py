"""The canned demo scenario that every mock answers from (mocks/scenario.json)."""
import json
from functools import lru_cache

from . import config


@lru_cache
def load() -> dict:
    return json.loads((config.ROOT / "mocks" / "scenario.json").read_text(encoding="utf-8"))


def for_event(event_id: str) -> dict:
    return load()["by_event"].get(event_id, {})


def for_decision(flag_id: str, action: str) -> dict:
    return load()["by_decision"].get(f"{flag_id}:{action}", {})
