"""Mock: ignores incoming forms, sends nothing."""
from app.core import models as m


def parse(form: dict) -> list[m.InboundEvent]:
    return []


def send(message: m.OutboundMessage) -> m.OutboundMessage:
    return message.model_copy(update={"status": "simulated"})
