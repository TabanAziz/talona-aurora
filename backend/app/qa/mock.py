"""Mock: canned answer per scenario event."""
from app.core import models as m
from app.core import scenario


def answer(event: m.InboundEvent, facts: list[m.Fact]) -> m.Answer | None:
    raw = scenario.for_event(event.id).get("answer")
    return m.Answer.model_validate(raw) if raw else None
