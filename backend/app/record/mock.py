"""Mock: canned project, history and record updates per scenario event."""
from app.core import models as m
from app.core import scenario


def project() -> m.Project:
    return m.Project.model_validate(scenario.load()["project"])


def baseline() -> list[m.RecordEntry]:
    return [m.RecordEntry.model_validate(e) for e in scenario.load()["baseline_record"]]


def apply(event: m.InboundEvent, facts: list[m.Fact]) -> m.RecordUpdate:
    return m.RecordUpdate.model_validate(scenario.for_event(event.id).get("record_update", {}))
