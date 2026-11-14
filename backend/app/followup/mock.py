"""Mock: no follow-up questions, so a scenario that only mocks this area stays quiet."""
from datetime import datetime

from app.core import models as m


def gaps(now: datetime) -> list:
    return []


def react(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.OutboundMessage]:
    return []
