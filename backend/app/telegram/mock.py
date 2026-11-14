"""Mock: accepts only updates that carry a prepared event, sends nothing."""
from app.core import models as m


def parse(update: dict) -> list[m.InboundEvent]:
    raw = update.get("aurora_event")
    return [m.InboundEvent.model_validate(raw)] if raw else []


def send(message: m.OutboundMessage) -> m.OutboundMessage:
    return message.model_copy(update={"status": "simulated"})
