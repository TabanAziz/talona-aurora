"""Machines are told about a drawing change like a crew: a notice in their queue and an open confirmation in the
waiting list. A machine fetches its notices and confirms by naming the revision it loaded. Nothing here calls a
model, and nothing here decides, holds, releases or changes the plan. Spec: docs/specs/machines.md."""
import hashlib
import json
from datetime import datetime, timezone

from app.core import config, models as m, pipeline
from app.core.registry import area
from app.core.store import store

REGISTRY = config.ROOT / "data" / "machines.json"
NOTICES = "machine_notices"
CONFIRMATIONS = "machine_confirmations"
DELIVERED = {"sent", "simulated"}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _now(floor: datetime | None = None) -> datetime:
    """The time of the latest event, like the start check, so a replay and a test answer the same on every laptop.

    A machine acts after what it was told, so the moment is never earlier than the notice it answers.
    """
    times = [moment for moment in (_time(event.get("received_at")) for event in store().list("events")) if moment]
    if floor is not None:
        times.append(floor)
    if not times:
        times = [moment for moment in (_time(entry.get("at")) for entry in store().list("record")) if moment]
    return max(times) if times else datetime(1970, 1, 1, tzinfo=timezone.utc)


def _key(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:16]


def _notice_id(sheet: str, revision: str, machine_id: str) -> str:
    # The crew notice's id scheme, so the escalation ladder finds a machine's notice as it finds a crew's.
    return "o-revision-" + hashlib.sha256("\0".join((sheet, revision, machine_id)).encode()).hexdigest()[:24]


def _waiting_id(machine_id: str, sheet: str, revision: str) -> str:
    # The record's id scheme for a crew's confirmation, so a later revision closes a machine's item the same way.
    identity = json.dumps(["ack", machine_id, sheet, revision], ensure_ascii=True)
    return "w-" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def registry() -> list[m.Machine]:
    """The committed registry. The store holds a copy from the last reset, which is what every area reads."""
    if config.project_directory.get() is not None:
        path = config.data_dir() / "seed.json"
        rows = json.loads(path.read_text(encoding="utf-8")).get("machines", [])
    else:
        rows = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return [m.Machine.model_validate(row) for row in rows]


def machines() -> list[m.Machine]:
    stored = store().list("machines")
    return [m.Machine.model_validate(row) for row in stored] if stored else registry()


def _machine(machine_id: str) -> m.Machine:
    found = next((machine for machine in machines() if machine.id == machine_id), None)
    if found is None:
        raise KeyError(machine_id)
    return found


def _current(sheet: str) -> m.Fact | None:
    lookup = getattr(area("record"), "current_revision", None)
    if lookup is not None:
        return lookup(sheet)
    revisions = [m.Fact.model_validate(fact) for fact in store().list("facts")
                 if fact.get("type") == "drawing_revision" and (fact.get("data") or {}).get("sheet") == sheet]
    return revisions[-1] if revisions else None


def _diff(sheet: str, revision: str) -> dict | None:
    return next((raw for raw in reversed(store().list("diffs"))
                 if raw.get("sheet") == sheet and raw.get("to_rev") == revision), None)


def _acknowledged(machine_id: str, sheet: str, revision: str) -> bool:
    return any(fact.get("type") == "acknowledgement" and (fact.get("data") or {}).get("crew") == machine_id
               and fact["data"].get("sheet") == sheet and fact["data"].get("revision") == revision
               for fact in store().list("facts"))


def _due(units: list[str], since: datetime) -> datetime | None:
    """The start of the earliest planned task in these units that is not done and has not ended by the plan."""
    plan = store().get("plan", "current") or {}
    starts = []
    for task in plan.get("tasks", []):
        if task.get("unit") not in units or task.get("status") == "done":
            continue
        end = _time(task.get("end"))
        if end is not None and end < since:
            continue
        start = _time(task.get("start"))
        if start is not None:
            starts.append(start)
    return min(starts) if starts else None


def react(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.OutboundMessage]:
    """A current revision of a sheet a machine loads, for units it works in, puts a notice in its queue and opens
    its confirmation. The caller delivers the messages; the waiting items and the notice details are stored here."""
    messages = []
    s = store()
    for fact in facts:
        if fact.event_id != event.id or fact.type != "drawing_revision":
            continue
        sheet, revision = _text(fact.data.get("sheet")), _text(fact.data.get("revision"))
        units = [unit for unit in fact.data.get("units") or [] if isinstance(unit, str)]
        if not sheet or not revision or not units:
            continue
        latest = _current(sheet)
        if latest is None or latest.id != fact.id:
            continue
        diff = _diff(sheet, revision)
        change = _text(fact.data.get("change")) or (diff or {}).get("summary")
        for machine in machines():
            covered = [unit for unit in units if unit in machine.units]
            if sheet not in machine.sheets or not covered or _acknowledged(machine.id, sheet, revision):
                continue
            notice_id = _notice_id(sheet, revision, machine.id)
            waiting_id = _waiting_id(machine.id, sheet, revision)
            if s.get("waiting", waiting_id) is None:
                s.put("waiting", waiting_id, m.WaitingItem(
                    id=waiting_id, on=machine.id, what=f"Confirm {sheet} Rev {revision}", since=event.received_at,
                    due=_due(covered, event.sent_at), source_event_ids=[event.id]))
            if s.get(NOTICES, notice_id) is None:
                s.put(NOTICES, notice_id, {
                    "id": notice_id, "machine_id": machine.id, "sheet": sheet, "revision": revision,
                    "replaces": _text(fact.data.get("replaces")), "units": covered, "change": change,
                    "waiting_id": waiting_id, "received_at": None,
                })
            text = f"{sheet} Rev {revision} is current. "
            if change:
                text += change.rstrip(".") + ". "
            text += f"Load Rev {revision} and confirm it before working in {', '.join(covered)}."
            messages.append(m.OutboundMessage(
                id=notice_id, channel="machine", to=machine.id, text=text,
                media_url=(diff or {}).get("after_geometry_url"),
                reason="Drawing revision needs machine confirmation", created_at=event.received_at))
    return messages


def send(message: m.OutboundMessage) -> m.OutboundMessage:
    """The machine fetches its notices, so putting the notice in its queue is the whole send.

    Every registered machine is simulated, and "sent" is kept for a message that left through a real channel, so
    the notice is marked simulated like a crew notice on a mocked channel.
    """
    return message.model_copy(update={"status": "simulated"})


def notices(machine_id: str) -> list[m.MachineNotice]:
    """The notices this machine has not confirmed, oldest first. The first fetch of each is when it was received."""
    with pipeline._lock:
        _machine(machine_id)
        s = store()
        found = []
        for row in s.list(NOTICES):
            if row.get("machine_id") != machine_id:
                continue
            message = s.get("outbox", row["id"])
            waiting = s.get("waiting", row["waiting_id"])
            if message is None or message.get("status") not in DELIVERED or waiting is None \
                    or waiting.get("status") != "open":
                continue
            # A machine works its queue in order, so a notice a newer revision replaced must not be loaded.
            latest = _current(row["sheet"])
            if latest is not None and _text(latest.data.get("revision")) != row["revision"]:
                continue
            sent_at = _time(message.get("created_at"))
            if row.get("received_at") is None:
                received = _now(sent_at)
                row = {**row, "received_at": received.isoformat()}
                s.put(NOTICES, row["id"], row)
                s.put("record", f"r-machine-received-{row['id']}", m.RecordEntry(
                    id=f"r-machine-received-{row['id']}", at=received, kind="notice",
                    title=f"{machine_id} received {row['sheet']} Rev {row['revision']}",
                    detail=message.get("text"), actor=machine_id, source_event_ids=waiting.get("source_event_ids", []),
                    refs={"machine": machine_id, "sheet": row["sheet"], "revision": row["revision"],
                          "message": row["id"]}))
            diff = _diff(row["sheet"], row["revision"])
            found.append(m.MachineNotice(
                id=row["id"], machine_id=machine_id, sheet=row["sheet"], revision=row["revision"],
                replaces=row.get("replaces"), units=row.get("units") or [], change=row.get("change"),
                diff_id=(diff or {}).get("id"), geometry_url=(diff or {}).get("after_geometry_url"),
                sent_at=sent_at, received_at=_time(row["received_at"]), due=_time(waiting.get("due")),
                waiting_id=row["waiting_id"]))
        return sorted(found, key=lambda notice: notice.sent_at)


def _last_load(machine_id: str, sheet: str) -> dict | None:
    return next((fact for fact in reversed(store().list("facts")) if fact.get("type") == "acknowledgement"
                 and (fact.get("data") or {}).get("crew") == machine_id and fact["data"].get("sheet") == sheet), None)


def _known(sheet: str, revision: str) -> bool:
    return any(fact.get("type") == "drawing_revision" and (fact.get("data") or {}).get("sheet") == sheet
               and revision in (_text(fact["data"].get("revision")), _text(fact["data"].get("replaces")))
               for fact in store().list("facts"))


def confirm(machine_id: str, request: m.MachineConfirmRequest) -> m.MachineConfirmation:
    """Store the revision the machine loaded. Only the current revision closes its confirmation."""
    with pipeline._lock:
        machine = _machine(machine_id)
        s = store()
        project = s.get("project", "current") or {}
        if request.sheet not in project.get("sheets", []):
            raise ValueError(f"{request.sheet} is not a sheet of this project. Nothing was confirmed.")
        latest = _current(request.sheet)
        current = _text(latest.data.get("revision")) if latest is not None else None
        if current is None or not _known(request.sheet, request.revision):
            raise ValueError(f"{request.sheet} has no Rev {request.revision} on record. Nothing was confirmed.")
        # A repeat of the machine's last load is the same confirmation; loading another revision in between is a new
        # one, so the latest load is always on record for the start check.
        previous = _last_load(machine_id, request.sheet)
        if previous is not None and previous["data"].get("revision") == request.revision:
            stored = s.get(CONFIRMATIONS, "mc-" + previous["id"].removeprefix("f-machine-"))
            if stored is not None and stored.get("current_revision") == current:
                return m.MachineConfirmation.model_validate(stored)
        key = _key(machine_id, request.sheet, request.revision, current, previous["id"] if previous else "")

        notice = s.get(NOTICES, _notice_id(request.sheet, current, machine_id))
        sent = s.get("outbox", notice["id"]) if notice else None
        at = _now(_time(sent.get("created_at")) if sent else None)
        text = f"{machine_id} loaded {request.sheet} Rev {request.revision}."
        event = m.InboundEvent(id=f"e-machine-{key}", channel="machine", sent_at=at, received_at=at,
                               sender=machine_id, sender_role=machine.kind, text=text)
        fact = m.Fact(id=f"f-machine-{key}", event_id=event.id, type="acknowledgement",
                      subject=f"{machine_id} confirmed {request.sheet} Rev {request.revision}",
                      data={"crew": machine_id, "sheet": request.sheet, "revision": request.revision,
                            "machine": machine_id},
                      confidence=1, quote=text)
        s.put("events", event.id, event)
        s.put("facts", fact.id, fact)

        status = "confirmed" if request.revision == current else "outdated"
        closed = None
        if status == "confirmed":
            waiting_id = _waiting_id(machine_id, request.sheet, request.revision)
            waiting = s.get("waiting", waiting_id)
            if waiting is not None and waiting.get("status") == "open":
                sources = waiting.get("source_event_ids", [])
                s.put("waiting", waiting_id, {**waiting, "status": "done",
                                              "source_event_ids": [*sources, event.id]})
                closed = waiting_id
            s.put("record", f"r-{fact.id}", m.RecordEntry(
                id=f"r-{fact.id}", at=at, kind="acknowledgement", title=fact.subject,
                detail=f"Loaded {request.sheet} Rev {request.revision}.", actor=machine_id,
                source_event_ids=[event.id],
                refs={"crew": machine_id, "sheet": request.sheet, "revision": request.revision,
                      "machine": machine_id, "fact": fact.id}))
        confirmation = m.MachineConfirmation(
            id=f"mc-{key}", machine_id=machine_id, sheet=request.sheet, revision=request.revision,
            current_revision=current, status=status, confirmed_at=at, event_id=event.id, waiting_id=closed)
        s.put(CONFIRMATIONS, confirmation.id, confirmation)
        return confirmation
