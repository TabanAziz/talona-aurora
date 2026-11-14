"""Mock: canned facts per scenario event."""
from app.core import models as m
from app.core import scenario


def extract(event: m.InboundEvent) -> list[m.Fact]:
    return [m.Fact.model_validate(f) for f in scenario.for_event(event.id).get("facts", [])]
