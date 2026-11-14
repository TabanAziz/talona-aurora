"""Mock: canned outbound messages per scenario event, never sent anywhere."""
from app.core import models as m
from app.core import scenario


def react(event: m.InboundEvent, facts: list[m.Fact], flags: list[m.Flag], answer: m.Answer | None) -> list[m.OutboundMessage]:
    return [m.OutboundMessage.model_validate(o) for o in scenario.for_event(event.id).get("outbox", [])]
