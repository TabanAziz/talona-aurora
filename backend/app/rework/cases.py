"""A change that arrives after the work was built: the record says work already started from the drawing it replaces.

Aurora only reacts: it names the rework, tells the crew not to cover or finish the built work, tells the
superintendent and opens one waiting item for the decision. It never decides and never raises a flag, because the
work has started and the drawing rules only look at work that has not begun.
"""
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from app.core import config, models as m
from app.core.registry import area
from app.core.store import store
from app.live import directory

SUPERINTENDENT = "Superintendent"
WORK_TYPES = {"work_started", "work_planned"}
CREW_CHANNEL: m.Channel = "telegram"


@dataclass(frozen=True)
class Case:
    """One unit whose built work predates the revision, with what the record and the plan say about it."""

    id: str
    unit: str
    crew: str
    diff: m.DrawingDiff
    work_event: m.InboundEvent
    revision_event: m.InboundEvent
    task: m.Task | None = None
    work_hours: float | None = None
    dependents: list[str] = field(default_factory=list)

    @property
    def hours_before(self) -> float:
        return (self.revision_event.received_at - self.work_event.received_at).total_seconds() / 3600


def _when(value: object) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _diff(sheet: str, revision: str) -> m.DrawingDiff | None:
    return next((m.DrawingDiff.model_validate(raw) for raw in reversed(store().list("diffs"))
                 if raw["sheet"] == sheet and raw["to_rev"] == revision), None)


def _plan() -> m.Plan | None:
    raw = store().get("plan", "current")
    return m.Plan.model_validate(raw) if raw else None


def _working_days(first, last) -> int:
    count, day = 0, first
    while day < last:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count += 1
    return count


def _working_hours(task: m.Task) -> float | None:
    """The plan's own duration for the task, the same rule the schedule uses for its rework assumption."""
    if task.start.date() == task.end.date():
        return (task.end - task.start).total_seconds() / 3600
    daily = (task.end.hour * 60 + task.end.minute - task.start.hour * 60 - task.start.minute) / 60
    if daily <= 0:
        return None
    return daily * (_working_days(task.start.date(), task.end.date()) + 1)


def _built_work(unit: str, replaced: str | None, revision_event: m.InboundEvent):
    """The latest work report for the unit before the revision that names the replaced revision or none."""
    best: tuple[m.Fact, m.InboundEvent] | None = None
    for raw in store().list("facts"):
        if raw["type"] not in WORK_TYPES or raw["data"].get("unit") != unit:
            continue
        stated = _text(raw["data"].get("revision"))
        if stated is not None and replaced is not None and stated != replaced:
            continue
        stored = store().get("events", raw["event_id"])
        if stored is None:
            continue
        work_event = m.InboundEvent.model_validate(stored)
        if raw["type"] == "work_started":
            if work_event.received_at >= revision_event.received_at:
                continue
        else:
            start = _when(raw["data"].get("start"))
            if start is None or start >= revision_event.received_at:
                continue
        if best is None or work_event.received_at > best[1].received_at:
            best = (m.Fact.model_validate(raw), work_event)
    return best or (None, None)


def _crew(fact: m.Fact, event: m.InboundEvent, task: m.Task | None) -> str:
    stated = _text(fact.data.get("crew"))
    if stated:
        return stated
    mapped = _crew_name(event.sender)
    if mapped is not None:
        return mapped
    return task.crew if task is not None else _superintendent()


def _crew_name(sender: str | None) -> str | None:
    contact = directory.lookup(sender or "") or directory.resolve(CREW_CHANNEL, sender)
    if contact is None or not contact.known:
        return None
    return contact.name if contact.kind == "crew" else (contact.crew or contact.name)


def cases(event: m.InboundEvent, facts: list[m.Fact]) -> list[Case]:
    """Every unit a revision touches where the record already holds work built from the replaced drawing."""
    found: list[Case] = []
    plan = _plan()
    tasks = {task.id: task for task in plan.tasks} if plan else {}
    for fact in facts:
        if fact.event_id != event.id or fact.type != "drawing_revision":
            continue
        sheet, revision = _text(fact.data.get("sheet")), _text(fact.data.get("revision"))
        if not sheet or not revision:
            continue
        diff = _diff(sheet, revision)
        if diff is None:
            continue
        replaced = _text(fact.data.get("replaces")) or diff.from_rev
        for unit in [unit for unit in fact.data.get("units") or [] if _text(unit)]:
            work, work_event = _built_work(unit, replaced, event)
            if work is None or work_event is None:
                continue
            task = tasks.get(_text(work.data.get("task")) or "")
            dependents = [other.name for other in tasks.values() if task is not None and task.id in other.depends_on]
            identity = hashlib.sha256(f"{diff.id}\0{unit}".encode()).hexdigest()[:24]
            found.append(Case(
                id=f"rw-{identity}", unit=unit, crew=_crew(work, work_event, task), diff=diff, work_event=work_event,
                revision_event=event, task=task, work_hours=_working_hours(task) if task else None,
                dependents=dependents,
            ))
    return found


def _media(diff: m.DrawingDiff) -> str | None:
    """The crop the drawing renderer saved for the overlay, so the crew sees the changed part."""
    if diff.overlay_url.startswith("/media/files/"):
        for name in ("crop.png", "crop.svg"):
            url = str(PurePosixPath(diff.overlay_url).with_name(name))
            base = (config.data_dir() / "files").resolve()
            target = (base / url.removeprefix("/media/files/")).resolve()
            if base in target.parents and target.is_file():
                return url
    return diff.overlay_url


def _superintendent() -> str:
    return next((person.name for person in directory.people() if (person.role or "").lower() == "superintendent"),
                SUPERINTENDENT)


def _hours(value: float | None) -> str:
    if value is None:
        return "an unknown number of hours"
    return f"{int(value)} hours" if float(value).is_integer() else f"{round(value, 1)} hours"


def _change(case: Case) -> str:
    """The change without its own full stop, so the caller can end the sentence exactly once."""
    if case.diff.summary:
        return f"{case.diff.sheet} Rev {case.diff.to_rev}: {case.diff.summary.strip().removesuffix('.')}"
    return f"{case.diff.sheet} Rev {case.diff.to_rev} changed the drawing"


def _estimate(case: Case) -> str:
    if case.task is None or case.work_hours is None:
        return "The plan holds no task for this work, so no working hours are given for a redo."
    later = ""
    if len(case.dependents) == 1:
        later = f"; {case.dependents[0]} depends on it"
    elif len(case.dependents) == 2:
        later = f"; {case.dependents[0]} and {case.dependents[1]} depend on it"
    elif case.dependents:
        later = f"; {len(case.dependents)} later tasks depend on it"
    return f"If it is redone once the plan gives {_hours(case.work_hours)} for {case.task.name} ({case.task.id}){later}."


def _crew_text(case: Case) -> str:
    return (f"Built before the change: work in {case.unit} was reported {_hours(case.hours_before)} before "
            f"{case.diff.sheet} Rev {case.diff.to_rev} arrived. {_change(case)}. Do not cover or finish the built work "
            f"until the superintendent decides the rework. {_estimate(case)}")


def _superintendent_text(case: Case) -> str:
    return (f"Rework in {case.unit}: work was reported {_hours(case.hours_before)} before "
            f"{case.diff.sheet} Rev {case.diff.to_rev} arrived. {_change(case)}. {_estimate(case)} "
            f"Decide the rework in {case.unit}.")


def _notice(case: Case, kind: str, to: str, text: str, reason: str) -> m.OutboundMessage:
    return m.OutboundMessage(
        id=f"o-rework-{case.id}-{kind}", channel=CREW_CHANNEL, to=to, text=text, media_url=_media(case.diff),
        reason=reason, created_at=case.revision_event.received_at)


def handle(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.OutboundMessage]:
    """One change entry, one crew message, one superintendent message and one waiting item, once per case.

    The messages are returned for the caller's delivery path, so they leave the app the same way as every notice.
    """
    messages: list[m.OutboundMessage] = []
    for case in cases(event, facts):
        entry_id = f"r-rework-{case.id}"
        if store().get("record", entry_id) is None:
            refs = {"rework": case.id, "diff": case.diff.id, "unit": case.unit}
            if case.task is not None:
                refs["task"] = case.task.id
            store().put("record", entry_id, m.RecordEntry(
                id=entry_id, at=case.revision_event.received_at, kind="change", title="Built before the change",
                detail=_superintendent_text(case), actor="Aurora",
                source_event_ids=[case.work_event.id, case.revision_event.id], refs=refs))
        waiting_id = f"w-rework-{case.id}"
        if store().get("waiting", waiting_id) is None:
            store().put("waiting", waiting_id, m.WaitingItem(
                id=waiting_id, on=_superintendent(), what=f"Decide the rework in {case.unit}",
                since=case.revision_event.received_at,
                source_event_ids=[case.work_event.id, case.revision_event.id]))
        crew = _notice(case, "crew", case.crew, _crew_text(case), "Work built from the replaced drawing")
        superintendent = _notice(
            case, "super", _superintendent(), _superintendent_text(case), "Rework decision for the superintendent")
        messages.extend([area("guest").bind_delivery(crew, [case.work_event.id]),
                         area("guest").bind_delivery(superintendent, [])])
    return messages
