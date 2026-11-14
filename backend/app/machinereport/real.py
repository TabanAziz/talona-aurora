"""A machine's report of what it found, turned into an event and facts by code. Spec: docs/specs/machines.md.

A wall report names a wall of a sheet and the line where the machine measured it. The line is compared with that
wall in the geometry of every revision of the sheet on record. A match with a superseded revision whose wall the
current revision changed raises one stale drawing flag per sheet, unit and wall; a match with the current revision,
or with none, is only a record entry. A delivery report names an item of the plan and how many arrived, and becomes a
delivery fact; the existing resource rule compares it with the plan and raises the plan deviation flag when the count
differs. No step here calls a model, and nothing here decides, holds or changes the plan.
"""
import hashlib
import json
import math
import re
from datetime import timezone

from app.core import config
from app.core import models as m
from app.core import pipeline
from app.core.registry import area
from app.core.store import store

# Both ends of a measured line must lie this close to the wall's ends. Chosen for the demo, not measured.
TOLERANCE_MM = 50.0
NOT_READ_YET = "This kind of report is not read yet."
PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")


def _register_geometry(sheet: str, revision: str) -> dict | None:
    """The plan geometry of one revision from the drawing register, the same files the robot loads."""
    if not _safe(sheet) or not _safe(revision):
        return None
    path = config.drawings_dir() / sheet / revision / "geometry.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _register_revisions(sheet: str) -> list[str]:
    folder = config.drawings_dir() / sheet
    if not _safe(sheet) or not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if (p / "geometry.json").is_file())


def _safe(name: object) -> bool:
    """Sheet and revision become path parts, so only plain names are allowed."""
    return isinstance(name, str) and bool(name) and all(ch.isalnum() or ch in "-_." for ch in name) \
        and name not in (".", "..")


def _wall(geometry: dict | None, wall_id: str) -> dict | None:
    if not geometry:
        return None
    return next((w for w in geometry.get("walls", []) if w.get("id") == wall_id), None)


def _ends_match(line: m.MeasuredLine, wall: dict) -> bool:
    def near(ax, ay, bx, by):
        return math.hypot(ax - bx, ay - by) <= TOLERANCE_MM

    forward = near(line.x1, line.y1, wall["x1"], wall["y1"]) and near(line.x2, line.y2, wall["x2"], wall["y2"])
    backward = near(line.x1, line.y1, wall["x2"], wall["y2"]) and near(line.x2, line.y2, wall["x1"], wall["y1"])
    return forward or backward


def _shape(wall: dict | None) -> tuple | None:
    return None if wall is None else (wall["x1"], wall["y1"], wall["x2"], wall["y2"], wall.get("thickness"))


def _revision_facts(sheet: str) -> list[tuple[m.Fact, m.InboundEvent]]:
    """Every revision fact of the sheet that arrived, oldest first."""
    s = store()
    events = {raw["id"]: raw for raw in s.list("events")}
    found = []
    for raw in s.list("facts"):
        data = raw.get("data") or {}
        if raw.get("type") != "drawing_revision" or data.get("sheet") != sheet or raw.get("event_id") not in events:
            continue
        if not isinstance(data.get("revision"), str) or not data["revision"].strip():
            continue
        found.append((m.Fact.model_validate(raw), m.InboundEvent.model_validate(events[raw["event_id"]])))
    found.sort(key=lambda pair: (pair[1].sent_at, pair[1].received_at, pair[0].id))
    return found


def _on_record(sheet: str) -> tuple[str | None, set[str], set[str]]:
    """The current revision of the sheet, every revision on record and the superseded ones."""
    facts = _revision_facts(sheet)
    superseded = {f.data["replaces"].strip() for f, _ in facts
                  if isinstance(f.data.get("replaces"), str) and f.data["replaces"].strip()}
    named = {f.data["revision"].strip() for f, _ in facts}
    current = [f.data["revision"].strip() for f, _ in facts if f.data["revision"].strip() not in superseded]
    return (current[-1] if current else None), named | superseded, superseded


def _issuance(sheet: str, revision: str) -> tuple[m.Fact, m.InboundEvent] | None:
    """The message that brought a revision: the first revision fact that names it."""
    return next(((f, e) for f, e in _revision_facts(sheet) if f.data["revision"].strip() == revision), None)


def _machine(machine_id: str) -> m.Machine:
    found = next((machine for machine in area("machine").machines() if machine.id == machine_id), None)
    if found is None:
        raise KeyError(machine_id)
    return found


def _plain(value: object) -> bool:
    """A name a machine may send: the record and later a model prompt quote it, so it can carry no sentence."""
    return isinstance(value, str) and PLAIN.fullmatch(value) is not None


def _event_id(machine_id: str, report_id: str) -> str:
    if _plain(report_id):
        return f"e-machine-{machine_id}-{report_id}"
    return f"e-machine-{machine_id}-{hashlib.sha256(report_id.encode()).hexdigest()[:16]}"


def _num(value: float) -> str:
    return f"{value:g}"


def _known_names(request: m.MachineReportRequest) -> dict[str, str]:
    """The unit, sheet and wall the project really has. Only these are ever repeated in text, so a name a machine
    made up never reaches the record or a later prompt that quotes it."""
    project = store().get("project", "current") or {}
    known = {}
    if _plain(request.unit) and request.unit in project.get("units", []):
        known["unit"] = request.unit
    if _plain(request.sheet) and request.sheet in project.get("sheets", []):
        known["sheet"] = request.sheet
        if _plain(request.wall) and any(_wall(_register_geometry(request.sheet, rev), request.wall)
                                        for rev in _register_revisions(request.sheet)):
            known["wall"] = request.wall
    return known


def _delivery_items() -> dict[str, str]:
    """The plan's delivery items by casefold, so a report stores the name the plan uses."""
    plan = store().get("plan", "current") or {}
    return {row["item"].casefold(): row["item"] for row in plan.get("resources", [])
            if row.get("kind") == "delivery" and isinstance(row.get("item"), str) and row["item"].strip()}


def _text(machine_id: str, request: m.MachineReportRequest) -> str:
    """The event text, written by code from the fields, so evidence and the record can quote it."""
    if request.kind == "delivery":
        item = _delivery_items().get((request.item or "").casefold())
        when = request.observed_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        if item is None:
            return f"{machine_id} sent a delivery report with no item this plan has at {when}."
        readable = isinstance(request.count, (int, float)) and not isinstance(request.count, bool)
        count = _num(request.count) if readable else "an unreadable count of"
        return f"{machine_id} reports {count} {item} arrived at {when}."
    names = _known_names(request)
    if request.kind == "wall" and request.line is not None and len(names) == 3:
        line = request.line
        return (f"{machine_id} measured wall {request.wall} in {request.unit} on {request.sheet} "
                f"from ({_num(line.x1)}, {_num(line.y1)}) to ({_num(line.x2)}, {_num(line.y2)}).")
    fields = [f"{key} {value}" for key, value in names.items()]
    if request.line is not None:
        line = request.line
        fields.append(f"line ({_num(line.x1)}, {_num(line.y1)}) to ({_num(line.x2)}, {_num(line.y2)})")
    return f"{machine_id} sent a {request.kind} report" + (f": {', '.join(fields)}." if fields else ".")


def _problem(request: m.MachineReportRequest) -> str | None:
    """Why code cannot read the report, in one plain sentence that repeats no name the project does not have."""
    if request.kind not in ("wall", "delivery"):
        return NOT_READ_YET
    if not _plain(request.report_id):
        return "The report id is not a plain name."
    if request.kind == "delivery":
        # The plan's item names carry spaces; only a name the plan really has is repeated in the event.
        if (request.item or "").casefold() not in _delivery_items():
            return "The delivery report names an item this plan has no delivery for."
        if request.count is None:
            return "The delivery report has no count."
        if isinstance(request.count, bool) or not math.isfinite(request.count) or request.count < 0:
            return "The delivery report has no count that can be read."
        return None
    known = _known_names(request)
    if not request.unit:
        return "The wall report names no unit."
    if "unit" not in known:
        return "The wall report names a unit this project does not have."
    if not request.sheet:
        return "The wall report names no sheet."
    if "sheet" not in known:
        return "The wall report names a sheet this project does not have."
    if not request.wall:
        return "The wall report names no wall."
    if "wall" not in known:
        return f"The wall report names a wall that no revision of {request.sheet} has."
    if request.line is None:
        return "The wall report has no measured line."
    return None


def _matched(request: m.MachineReportRequest) -> str | None:
    """The revision on record whose wall the line matches; the current one wins when several do."""
    current, known, _ = _on_record(request.sheet)
    matches = [rev for rev in sorted(known)
               if (wall := _wall(_register_geometry(request.sheet, rev), request.wall))
               and _ends_match(request.line, wall)]
    if current in matches:
        return current
    return matches[-1] if matches else None


def _subject(machine_id: str, request: m.MachineReportRequest, revision: str | None, current: str | None) -> str:
    where = f"wall {request.wall} in {request.unit}"
    if revision is None:
        return f"{machine_id} measured {where} at a position that matches no revision of {request.sheet} on record"
    verb = "puts" if revision == current else "put"
    return f"{machine_id} found {where} where {request.sheet} Rev {revision} {verb} it"


def report(machine_id: str, request: m.MachineReportRequest) -> m.MachineReportResult:
    machine = _machine(machine_id)
    try:
        return _read(machine, request)
    except KeyError as error:
        # The route answers a KeyError with "no machine named ... nothing was stored", which would be false here.
        raise RuntimeError(f"reading the report of {machine_id} failed") from error


def _read(machine: m.Machine, request: m.MachineReportRequest) -> m.MachineReportResult:
    machine_id = machine.id
    pipeline.ensure_ready()
    event_id = _event_id(machine_id, request.report_id)
    problem = _problem(request)
    result = m.MachineReportResult(
        report_id=request.report_id, machine_id=machine_id, event_id=event_id,
        status="not_understood" if problem else "understood", reason=problem,
    )
    stored = store().get("events", event_id)
    if stored is not None:
        facts = [m.Fact.model_validate(raw) for raw in store().list("facts") if raw.get("event_id") == event_id]
        revision = next((f.data.get("revision") for f in facts), None)
        return result.model_copy(update={
            "duplicate": True, "facts": facts, "matches_revision": revision,
            "status": "understood" if facts else "not_understood",
            "reason": None if facts else (problem or "The report could not be read."),
        })

    now = pipeline.now()
    observed = request.observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    event = m.InboundEvent(
        id=event_id, channel="machine", sent_at=min(observed, now), received_at=now,
        sender=machine_id, sender_role=machine.kind, text=_text(machine_id, request),
    )
    if problem:
        ingested = pipeline.observe(event, [])
        if ingested.duplicate:
            return result.model_copy(update={"duplicate": True})
        store().put("record", f"r-{event_id}", m.RecordEntry(
            id=f"r-{event_id}", at=event.received_at, kind="info",
            title=f"Report from {machine_id} not understood: {problem}", detail=event.text, actor=machine_id,
            source_event_ids=[event_id], refs={"machine": machine_id},
        ))
        return result

    if request.kind == "delivery":
        item = _delivery_items()[request.item.casefold()]
        fact = m.Fact(
            id=f"fact-{event_id}", event_id=event_id, type="delivery_actual",
            subject=f"{item}: {_num(request.count)} arrived",
            data={"item": item, "planned": None, "actual": request.count,
                  "date": observed.date().isoformat(), "machine": machine_id},
            confidence=1, quote=event.text,
        )
        ingested = pipeline.observe(event, [fact])
        return result.model_copy(update={"duplicate": ingested.duplicate, "facts": ingested.facts,
                                         "flags": ingested.flags})
    current, _, _ = _on_record(request.sheet)
    revision = _matched(request)
    fact = m.Fact(
        id=f"fact-{event_id}", event_id=event_id, type="other",
        subject=_subject(machine_id, request, revision, current),
        data={"observation": "as_built", "unit": request.unit, "sheet": request.sheet, "wall": request.wall,
              "revision": revision, "machine": machine_id},
        confidence=1, quote=event.text,
    )
    ingested = pipeline.observe(event, [fact])
    return result.model_copy(update={
        "duplicate": ingested.duplicate, "matches_revision": revision, "facts": ingested.facts,
        "flags": ingested.flags,
    })


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _task(unit: str) -> m.Task | None:
    """The plan's next task in the unit that is not done: the work a wall at the wrong place would affect."""
    plan = store().get("plan", "current") or {}
    tasks = [m.Task.model_validate(raw) for raw in plan.get("tasks", [])]
    open_tasks = sorted((t for t in tasks if t.unit == unit and t.status != "done"), key=lambda t: (t.start, t.id))
    return open_tasks[0] if open_tasks else None


def _evidence(event: m.InboundEvent, quote: str | None) -> m.Evidence:
    attachment = next((a.url for a in event.attachments if a.kind in ("pdf", "image") and a.url), None)
    return m.Evidence(event_id=event.id, channel=event.channel, sender=event.sender, at=event.sent_at,
                      quote=quote or event.transcript or event.text, attachment_url=attachment)


def evaluate(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.Flag]:
    """One stale drawing flag for a wall that stands where a superseded revision put it."""
    if event.channel != "machine" or not any(machine.id == event.sender for machine in area("machine").machines()):
        return []
    flags = []
    for fact in facts:
        data = fact.data
        if fact.event_id != event.id or fact.type != "other" or data.get("observation") != "as_built":
            continue
        sheet, unit, wall_id, matched = (data.get(key) for key in ("sheet", "unit", "wall", "revision"))
        machine_id = data.get("machine") or event.sender
        if not all(isinstance(value, str) and value for value in (sheet, unit, wall_id, matched)):
            continue
        current, _, superseded = _on_record(sheet)
        if current is None or matched == current or matched not in superseded:
            continue
        old = _wall(_register_geometry(sheet, matched), wall_id)
        new = _wall(_register_geometry(sheet, current), wall_id)
        if _shape(old) == _shape(new):
            continue
        issued = _issuance(sheet, current)
        flag_id = f"f-asbuilt-{_slug(sheet)}-{_slug(unit)}-{_slug(wall_id)}"
        previous_raw = store().get("flags", flag_id)
        previous = m.Flag.model_validate(previous_raw) if previous_raw else None
        task = _task(unit)
        change = issued[0].data.get("change") if issued else None
        summary = (f"{machine_id} measured wall {wall_id} in {unit} at its position in {sheet} Rev {matched}. "
                   f"Rev {current} is current and moved this wall.")
        if isinstance(change, str) and change.strip():
            summary += f" {change.strip().rstrip('.')}."
        affected = {"unit": unit, "sheet": sheet, "revision": current, "wall": wall_id, "machine": machine_id}
        if task is not None:
            affected.update({"crew": task.crew, "task": task.id})
        evidence = [_evidence(event, fact.quote)]
        if issued:
            evidence.append(_evidence(issued[1], issued[0].quote))
        diff = next((d for d in reversed(store().list("diffs")) if d.get("sheet") == sheet
                     and d.get("to_rev") == current), None)
        status = previous.status if previous else "open"
        # A crew confirming the new revision can resolve this flag, but a confirmation moves no wall: a wall still
        # measured at the old place reopens it unless a person decided on it.
        if status == "resolved" and not any(d.get("flag_id") == flag_id for d in store().list("decisions")):
            status = "open"
        flags.append(m.Flag(
            id=flag_id, type="stale_drawing", severity="high",
            title=f"Wall {wall_id} in {unit} stands where {sheet} Rev {matched} put it",
            summary=summary, status=status,
            raised_at=previous.raised_at if previous else event.received_at,
            work_starts_at=task.start if task else None, affected=affected, evidence=evidence,
            diff_id=diff["id"] if diff else (previous.diff_id if previous else None),
            proposal_id=previous.proposal_id if previous else None,
        ))
    return flags
