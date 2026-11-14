"""Mock: canned flags per scenario event."""
from app.core import models as m
from app.core import scenario


def evaluate(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.Flag]:
    raw = scenario.for_event(event.id).get("flags", {}).get("rules_sequence", [])
    return [m.Flag.model_validate(f) for f in raw]
