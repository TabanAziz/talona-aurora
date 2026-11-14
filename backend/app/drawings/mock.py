"""Mock: canned drawing diff per scenario event."""
from app.core import models as m
from app.core import scenario


def diffs_for(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.DrawingDiff]:
    return [m.DrawingDiff.model_validate(d) for d in scenario.for_event(event.id).get("diffs", [])]
