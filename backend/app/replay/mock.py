"""Mock: the events of the canned scenario, in order."""
from app.core import models as m
from app.core import scenario


def events() -> list[m.InboundEvent]:
    return [m.InboundEvent.model_validate(e) for e in scenario.load()["events"]]
