"""The full scenario from data/messages, in the order the channels delivered it."""
import json
from pathlib import Path

from pydantic import ValidationError

from app import demodata
from app.core import config
from app.core import models as m

EVENTS_FILE = config.ROOT / "data" / "messages" / "events.json"


class ReplayDataError(ValueError):
    pass


def load(path: Path) -> list[m.InboundEvent]:
    """Every delivery in the file, sorted by received_at; a repeated id keeps only its first delivery."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayDataError(f"cannot read {path.name}: {error}") from None
    if not isinstance(raw, list):
        raise ReplayDataError(f"{path.name} must hold a list of events")

    deliveries: list[m.InboundEvent] = []
    for n, item in enumerate(raw, start=1):
        try:
            deliveries.append(m.InboundEvent.model_validate(item))
        except ValidationError as error:
            raise ReplayDataError(f"{path.name} entry {n} is not an InboundEvent: {error}") from None

    # sorted() is stable, so deliveries with the same received_at keep their file order.
    events: list[m.InboundEvent] = []
    seen: set[str] = set()
    for event in sorted(deliveries, key=lambda e: e.received_at):
        if event.id in seen:
            continue
        seen.add(event.id)
        events.append(event)
    return events


def events() -> list[m.InboundEvent]:
    return demodata.shift_events(load(EVENTS_FILE))
