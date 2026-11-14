"""Mock: the scenario carries the transcript of each voice note."""
from app.core import models as m
from app.core import scenario


def stand_in(event_id: str) -> str | None:
    """The scenario's transcript for a voice note that has no audio file behind it."""
    return scenario.for_event(event_id).get("transcript")


def transcribe(event: m.InboundEvent) -> m.InboundEvent:
    transcript = stand_in(event.id)
    if transcript and not event.transcript:
        return event.model_copy(update={"transcript": transcript})
    return event
