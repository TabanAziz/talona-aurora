"""Mock: an empty mailbox, sends nothing."""
from app.core import models as m


def poll() -> list[m.InboundEvent]:
    return []


def send(message: m.OutboundMessage) -> m.OutboundMessage:
    return message.model_copy(update={"status": "simulated"})
