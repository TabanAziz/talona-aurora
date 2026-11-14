"""Mock: the machines from mocks/scenario.json, the notices the store already holds for them, and a confirmation
that is checked against the record but closes nothing. Spec: docs/specs/machines.md."""
import hashlib
from datetime import datetime, timezone

from app.core import models as m
from app.core import scenario
from app.core.registry import area
from app.core.store import store

CONFIRM = "Confirm {sheet} Rev {revision}"


def _time(value: object) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _now() -> datetime:
    times = [moment for moment in (_time(entry.get("at")) for entry in store().list("record")) if moment]
    return max(times) if times else datetime.now(timezone.utc)


def machines() -> list[m.Machine]:
    stored = store().list("machines")
    raw = stored if stored else scenario.load().get("machines", [])
    return [m.Machine.model_validate(row) for row in raw]


def _machine(machine_id: str) -> m.Machine:
    found = next((machine for machine in machines() if machine.id == machine_id), None)
    if found is None:
        raise KeyError(machine_id)
    return found


def notices(machine_id: str) -> list[m.MachineNotice]:
    _machine(machine_id)
    found = []
    for message in store().list("outbox"):
        if message.get("channel") != "machine" or message.get("to") != machine_id:
            continue
        for item in store().list("waiting"):
            if item.get("on") != machine_id or item.get("status") != "open":
                continue
            what = item.get("what") or ""
            if not what.startswith("Confirm ") or " Rev " not in what:
                continue
            sheet, revision = what.removeprefix("Confirm ").rsplit(" Rev ", 1)
            if sheet not in message.get("text", "") or revision not in message.get("text", ""):
                continue
            found.append(m.MachineNotice(
                id=message["id"], machine_id=machine_id, sheet=sheet, revision=revision,
                sent_at=_time(message.get("created_at")) or _now(), due=_time(item.get("due")),
                waiting_id=item["id"],
            ))
    return sorted(found, key=lambda notice: notice.sent_at)


def _current(sheet: str) -> str | None:
    lookup = getattr(area("record"), "current_revision", None)
    if lookup is not None:
        fact = lookup(sheet)
        return str(fact.data.get("revision")) if fact is not None else None
    revisions = [fact for fact in store().list("facts")
                 if fact.get("type") == "drawing_revision" and (fact.get("data") or {}).get("sheet") == sheet]
    return str(revisions[-1]["data"].get("revision")) if revisions else None


def _known(sheet: str, revision: str) -> bool:
    return any(fact.get("type") == "drawing_revision" and (fact.get("data") or {}).get("sheet") == sheet
               and revision in (str(fact["data"].get("revision")), str(fact["data"].get("replaces")))
               for fact in store().list("facts"))


def confirm(machine_id: str, request: m.MachineConfirmRequest) -> m.MachineConfirmation:
    _machine(machine_id)
    project = store().get("project", "current") or {}
    if request.sheet not in project.get("sheets", []):
        raise ValueError(f"{request.sheet} is not a sheet of this project. Nothing was confirmed.")
    current = _current(request.sheet)
    if current is None or not (request.revision == current or _known(request.sheet, request.revision)):
        raise ValueError(f"{request.sheet} has no Rev {request.revision} on record. Nothing was confirmed.")
    key = hashlib.sha256("\0".join((machine_id, request.sheet, request.revision)).encode()).hexdigest()[:16]
    return m.MachineConfirmation(
        id=f"mc-{key}", machine_id=machine_id, sheet=request.sheet, revision=request.revision,
        current_revision=current, status="confirmed" if request.revision == current else "outdated",
        confirmed_at=_now(), event_id=f"e-machine-{key}", waiting_id=None,
    )


def react(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.OutboundMessage]:
    """The mock tells no machine about a change; that is the real module's job."""
    return []


def send(message: m.OutboundMessage) -> m.OutboundMessage:
    """The machine channel is a queue the machine fetches from, so putting a notice there is the send."""
    return message.model_copy(update={"status": "simulated"})
