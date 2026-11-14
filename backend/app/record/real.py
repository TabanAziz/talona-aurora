"""Build the site record and pending confirmations from arrived facts."""
import hashlib
import json
from datetime import datetime

from app import demodata
from app.core import models as m
from app.core.store import store


def project() -> m.Project:
    return demodata.load().project


def baseline() -> list[m.RecordEntry]:
    return demodata.load().history


def _arrived_facts() -> list[tuple[m.Fact, m.InboundEvent]]:
    events = {item["id"]: m.InboundEvent.model_validate(item) for item in store().list("events")}
    return [
        (m.Fact.model_validate(item), events[item["event_id"]])
        for item in store().list("facts") if item["event_id"] in events
    ]


def _latest(types: set[str], **fields: str) -> m.Fact | None:
    matches = [
        (event.sent_at, event.received_at, index, fact)
        for index, (fact, event) in enumerate(_arrived_facts())
        if fact.type in types and all(fact.data.get(key) == value for key, value in fields.items())
        and (fact.type != "drawing_revision" or _text(fact.data.get("revision")))
    ]
    return max(matches, key=lambda item: item[:3])[3] if matches else None


def current_revision(sheet: str) -> m.Fact | None:
    """Return the latest unsuperseded sourced revision, or None when unknown."""
    revisions = [
        (event.sent_at, event.received_at, index, fact)
        for index, (fact, event) in enumerate(_arrived_facts())
        if fact.type == "drawing_revision" and fact.data.get("sheet") == sheet
        and _text(fact.data.get("revision"))
    ]
    superseded = {_text(item[3].data.get("replaces")) for item in revisions}
    current = [item for item in revisions if item[3].data["revision"] not in superseded]
    return max(current, key=lambda item: item[:3])[3] if current else None


def inspection_status(unit: str, inspection: str) -> m.Fact | None:
    """Return the newest inspection fact for this unit and inspection."""
    return _latest({"inspection_scheduled", "inspection_moved", "inspection_passed"}, unit=unit, inspection=inspection)


def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _waiting_id(kind: str, *parts: str) -> str:
    identity = json.dumps([kind, *parts], ensure_ascii=True)
    return "w-" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def _time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _confirmed(fact: m.Fact, crew: str) -> bool:
    arrived = _arrived_facts()
    issued_at = min((
        event.sent_at for issuance, event in arrived
        if issuance.type == "drawing_revision"
        and issuance.data.get("sheet") == fact.data["sheet"]
        and issuance.data.get("revision") == fact.data["revision"]
    ), default=None)
    return issued_at is not None and any(
        ack.type == "acknowledgement" and ack.data.get("crew") == crew
        and ack.data.get("sheet") == fact.data["sheet"]
        and ack.data.get("revision") == fact.data["revision"]
        and event.sent_at >= issued_at
        for ack, event in arrived
    )


def _revision_waiting(fact: m.Fact, event: m.InboundEvent) -> list[m.WaitingItem]:
    data = fact.data
    sheet, revision = _text(data.get("sheet")), _text(data.get("revision"))
    latest = current_revision(sheet) if sheet else None
    if not sheet or not revision or latest is None or latest.id != fact.id:
        return []
    units = data.get("units")
    if not isinstance(units, list) or not units:
        return []
    plan = store().get("plan", "current") or {}
    crews: dict[str, list[datetime]] = {}
    for task in plan.get("tasks", []):
        crew = _text(task.get("crew"))
        if task.get("unit") not in units or not crew or task.get("status") == "done":
            continue
        end = _time(task.get("end"))
        if end is not None and end < event.sent_at:
            continue
        due = _time(task.get("start"))
        crews.setdefault(crew, [])
        if due is not None:
            crews[crew].append(due)
    pending = []
    for crew, starts in crews.items():
        identity = _waiting_id("ack", crew, sheet, revision)
        existing = store().get("waiting", identity)
        if existing is not None or _confirmed(fact, crew):
            continue
        pending.append(m.WaitingItem(
            id=identity, on=crew, what=f"Confirm {sheet} Rev {revision}", since=event.received_at,
            due=min(starts) if starts else None, source_event_ids=[event.id],
        ))
    return pending


def _entry(event: m.InboundEvent, fact: m.Fact) -> m.RecordEntry:
    data = fact.data
    title = fact.subject
    kind = "change"
    if fact.type == "drawing_revision" and _text(data.get("sheet")) and _text(data.get("revision")):
        title = f"{data['sheet']} Rev {data['revision']} issued"
    elif fact.type == "acknowledgement":
        kind = "acknowledgement"
        if all(_text(data.get(key)) for key in ("crew", "sheet", "revision")):
            title = f"{data['crew']} confirmed {data['sheet']} Rev {data['revision']}"
    elif fact.type.startswith("inspection_"):
        state = fact.type.removeprefix("inspection_")
        title = " ".join(str(data[key]) for key in ("unit", "inspection") if data.get(key))
        title = f"{title or fact.subject} inspection {state}"
    elif fact.type in {"work_planned", "work_started", "question", "other"}:
        kind = "info"
    refs = {key: data[key] for key in ("sheet", "revision", "unit", "crew", "task") if _text(data.get(key))}
    refs["fact"] = fact.id
    if fact.type == "delivery_actual":
        refs["fact_type"] = fact.type
        for field, target in (("item", "item"), ("date", "resource_date")):
            value = _text(data.get(field))
            if value:
                refs[target] = value
    detail = _text(data.get("change")) or fact.quote
    reason = _text(data.get("reason"))
    if data.get("not_understood") is True and reason:
        detail = f"Reason: {reason}"
        if fact.quote:
            detail += f"\nSource: {fact.quote}"
    return m.RecordEntry(
        id=f"r-{fact.id}", at=event.sent_at, kind=kind, title=title,
        detail=detail, actor=event.sender,
        source_event_ids=[event.id], refs=refs,
    )


def apply(event: m.InboundEvent, facts: list[m.Fact]) -> m.RecordUpdate:
    """Return record and waiting changes; the pipeline persists the update."""
    # Only an entry these facts wrote blocks a second pass. A reprocessed event also appears in entries other parts
    # wrote about it (the clarifying answer, a notice), and those must not keep its facts out of the record.
    if any(event.id in entry.get("source_event_ids", []) and "fact" in (entry.get("refs") or {})
           for entry in store().list("record")):
        return m.RecordUpdate()
    update = m.RecordUpdate()
    pending_ids: set[str] = set()
    for fact in facts:
        if fact.event_id != event.id:
            continue
        entry = _entry(event, fact)
        if any(existing.id == entry.id for existing in update.entries):
            continue
        update.entries.append(entry)
        if fact.type == "drawing_revision":
            sheet, revision = _text(fact.data.get("sheet")), _text(fact.data.get("revision"))
            if sheet and revision:
                for item in store().list("waiting"):
                    identity = _waiting_id("ack", item["on"], sheet, revision)
                    if item["id"] == identity and item["status"] == "open" and identity not in update.waiting_close:
                        if _confirmed(fact, item["on"]):
                            update.waiting_close.append(identity)
            for item in _revision_waiting(fact, event):
                if item.id not in pending_ids:
                    pending_ids.add(item.id)
                    update.waiting_open.append(item)
        elif fact.type == "acknowledgement":
            keys = ("crew", "sheet", "revision")
            if all(_text(fact.data.get(key)) for key in keys):
                identity = _waiting_id("ack", *(fact.data[key] for key in keys))
                existing = store().get("waiting", identity)
                if existing and existing["status"] == "open" and identity not in update.waiting_close:
                    if _confirmed(fact, fact.data["crew"]):
                        update.waiting_close.append(identity)
        elif fact.type.startswith("inspection_"):
            unit, inspection = _text(fact.data.get("unit")), _text(fact.data.get("inspection"))
            if not unit or not inspection:
                continue
            latest = inspection_status(unit, inspection)
            if latest is None or latest.id != fact.id:
                continue
            identity = _waiting_id("inspection", unit, inspection)
            existing = store().get("waiting", identity)
            if fact.type == "inspection_passed":
                if existing and existing["status"] == "open":
                    update.waiting_close.append(identity)
            else:
                update.waiting_open.append(m.WaitingItem(
                    id=identity, on="Inspector (not specified)", what=f"Sign off {inspection} {unit}",
                    since=event.received_at, due=_time(fact.data.get("new_time") or fact.data.get("time")),
                    source_event_ids=[event.id],
                ))
    return update
