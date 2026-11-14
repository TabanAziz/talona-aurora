"""What Aurora learned: the standing rules from decisions, and the four patterns counted from the record.

The rules come from the store's `rules` collection written by the learning area. The applied count attributes
each standing-rule answer to the rule whose evidence it cites, so two rules never share one application.

The patterns are counts over the stored record, flags, decisions, waiting list and outbox. A pattern is shown
only with at least two cases, and its examples are record entries that the page can open. Nothing here is a
forecast and no percentage appears without its two numbers.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core import models as m
from app.core.store import store

DAY = timedelta(hours=24)
CHANGE_TYPES = {"drawing_revision", "inspection_scheduled", "inspection_moved", "inspection_passed"}


def _time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _moment(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _same_work(work: str, asked: str) -> bool:
    """The qa area's match: every word of the rule's work must appear in the question, prefix enough."""
    words = re.findall(r"[a-z]+", _norm(asked))
    return all(any(word.startswith(part[:4]) for word in words)
               for part in re.findall(r"[a-z]+", _norm(work)) if len(part) >= 4)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def _event_ids(sources: list[dict[str, Any]] | list[m.Evidence]) -> set[str]:
    return {source["event_id"] if isinstance(source, dict) else source.event_id for source in sources}


def _plan() -> m.Plan | None:
    raw = store().get("plan", "current")
    return m.Plan.model_validate(raw) if raw else None


def _facts() -> list[m.Fact]:
    return [m.Fact.model_validate(raw) for raw in store().list("facts")]


def _events() -> dict[str, m.InboundEvent]:
    return {event.id: event for event in (m.InboundEvent.model_validate(raw) for raw in store().list("events"))}


def _records() -> list[dict]:
    return store().list("record")


def _record_of_fact(record: list[dict], fact_id: str) -> str | None:
    for entry in record:
        if (entry.get("refs") or {}).get("fact") == fact_id:
            return entry["id"]
    return None


def _record_of_flag(record: list[dict], flag_id: str) -> str | None:
    wanted = f"r-flag-{flag_id}"
    return wanted if any(entry["id"] == wanted for entry in record) else None


def _tasks_by_unit(plan: m.Plan | None) -> dict[str, list[m.Task]]:
    tasks: dict[str, list[m.Task]] = {}
    for task in plan.tasks if plan else []:
        if task.unit:
            tasks.setdefault(task.unit, []).append(task)
    return tasks


def _affected_tasks(fact: m.Fact, by_unit: dict[str, list[m.Task]]) -> list[m.Task]:
    data = fact.data
    units: list[str] = []
    if fact.type == "drawing_revision":
        units = [str(unit) for unit in data.get("units") or [] if str(unit).strip()]
    elif data.get("unit"):
        units = [str(data["unit"])]
    found: list[m.Task] = []
    for unit in units:
        found.extend(by_unit.get(unit, []))
    return found


def _late_change(record: list[dict]) -> m.Pattern | None:
    plan = _plan()
    by_unit = _tasks_by_unit(plan)
    events = _events()
    late: list[str] = []
    total = 0
    for fact in _facts():
        if fact.type not in CHANGE_TYPES:
            continue
        tasks = _affected_tasks(fact, by_unit)
        event = events.get(fact.event_id)
        arrived = event.received_at if event else None
        example = _record_of_fact(record, fact.id)
        if not tasks or arrived is None or example is None:
            continue
        total += 1
        if any(timedelta(0) <= _moment(task.start) - _moment(arrived) < DAY for task in tasks):
            late.append(example)
    if len(late) < 2:
        return None
    return m.Pattern(
        id="p-late-change", kind="late_change",
        statement=f"{len(late)} of {total} changes arrived less than 24 hours before the work they affect.",
        count=len(late), total=total, examples=late,
        suggestion="Ask the architect to issue revisions before 14:00.",
    )


def _record_of_change_event(record: list[dict], event_id: str) -> str | None:
    for entry in record:
        refs = entry.get("refs") or {}
        if (event_id in (entry.get("source_event_ids") or []) and entry.get("kind") == "change"
                and (refs.get("sheet") or refs.get("unit"))):
            return entry["id"]
    return None


def _late_confirmation(record: list[dict]) -> list[m.Pattern]:
    """Per crew: confirmation items whose due passed without an acknowledgement before it."""
    by_crew: dict[str, list[dict]] = {}
    for item in store().list("waiting"):
        if not str(item.get("what", "")).startswith("Confirm "):
            continue
        crew = item.get("on")
        if isinstance(crew, str) and crew.strip():
            by_crew.setdefault(crew, []).append(item)
    now = _generated_at(record)
    patterns: list[m.Pattern] = []
    for crew, items in by_crew.items():
        lateness = 0
        examples: list[str] = []
        for item in items:
            due = _time(item.get("due"))
            if due is None or due > now:
                continue
            if _confirmed_before(item, due, record):
                continue
            example = None
            for event_id in item.get("source_event_ids") or []:
                example = _record_of_change_event(record, event_id)
                if example:
                    break
            if example is None:
                continue
            lateness += 1
            examples.append(example)
        if lateness < 2:
            continue
        patterns.append(m.Pattern(
            id=f"p-late-confirmation-{_slug(crew)}", kind="late_confirmation",
            statement=f"{crew} left {lateness} of {len(items)} changes unconfirmed before the work started.",
            count=lateness, total=len(items), examples=examples,
        ))
    return patterns


def _confirmed_before(item: dict, due: datetime, record: list[dict]) -> bool:
    if item.get("status") == "done":
        for entry in record:
            refs = entry.get("refs") or {}
            if (entry.get("kind") == "acknowledgement" and refs.get("crew") == item.get("on")
                    and f"Confirm {refs.get('sheet', '')} Rev {refs.get('revision', '')}" == item.get("what")):
                at = _time(entry.get("at"))
                return at is not None and at <= due
        # The record closed the item, so trust it even when the acknowledgement entry is not visible.
        return True
    return False


def _repeat_flag(record: list[dict]) -> list[m.Pattern]:
    """Flags of one type, grouped by type. The statement names every crew so the numbers cannot imply one crew."""
    # The spec groups by type and crew; the demo has one flag of each type per crew, so a same-crew pattern would
    # never appear. Grouping by type keeps the numbers real and gives R13 a visible pattern; the crews are named.
    groups: dict[str, list[m.Flag]] = {}
    for raw in store().list("flags"):
        flag = m.Flag.model_validate(raw)
        groups.setdefault(flag.type, []).append(flag)
    patterns: list[m.Pattern] = []
    for kind, flags in groups.items():
        if len(flags) < 2:
            continue
        examples = [_record_of_flag(record, flag.id) for flag in flags]
        if any(example is None for example in examples):
            continue
        crews = list(dict.fromkeys(str(flag.affected.get("crew")) for flag in flags if flag.affected.get("crew")))
        where = f" for the {', '.join(crews)}" if crews else ""
        patterns.append(m.Pattern(
            id=f"p-repeat-flag-{kind}", kind="repeat_flag",
            statement=f"{len(flags)} {kind.replace('_', ' ')} flags{where}.",
            count=len(flags), total=len(flags), examples=examples,
        ))
    return patterns


def _dismissed_flags(record: list[dict]) -> list[m.Pattern]:
    decisions = store().list("decisions")
    decided_ids = {decision["flag_id"] for decision in decisions}
    dismissed_ids = {decision["flag_id"] for decision in decisions if decision.get("action") == "dismiss"}
    groups: dict[str, list[m.Flag]] = {}
    for raw in store().list("flags"):
        flag = m.Flag.model_validate(raw)
        if flag.id in decided_ids:
            groups.setdefault(flag.type, []).append(flag)
    patterns: list[m.Pattern] = []
    for kind, flags in groups.items():
        dismissed = [flag for flag in flags
                     if flag.id in dismissed_ids or flag.status == "dismissed"]
        if len(dismissed) < 2:
            continue
        examples = [_record_of_flag(record, flag.id) for flag in dismissed]
        if any(example is None for example in examples):
            continue
        patterns.append(m.Pattern(
            id=f"p-dismissed-{kind}", kind="dismissed_flags",
            statement=f"{len(dismissed)} of {len(flags)} {kind.replace('_', ' ')} flags were dismissed.",
            count=len(dismissed), total=len(flags), examples=examples,
            suggestion="Stop flagging cases like these, or widen the rule that raises them.",
        ))
    return patterns


def _patterns(record: list[dict]) -> list[m.Pattern]:
    pattern = _late_change(record)
    patterns = [pattern] if pattern else []
    patterns.extend(_late_confirmation(record))
    patterns.extend(_repeat_flag(record))
    patterns.extend(_dismissed_flags(record))
    return patterns


def _generated_at(record: list[dict]) -> datetime:
    times = [at for at in (_time(entry.get("at")) for entry in record) if at is not None]
    return max(times) if times else datetime.now(timezone.utc)


def _positions(record: list[dict]) -> dict[str, int]:
    return {entry["id"]: index for index, entry in enumerate(record) if entry.get("id")}


def _standing_rules(record: list[dict]) -> list[m.StandingRule]:
    answers = store().list("answers")
    positions = _positions(record)
    matched = []
    for raw in store().list("rules"):
        if raw.get("status", "active") != "active":
            continue
        decision_id = str(raw.get("decision_id") or "")
        decided_at = _time(raw.get("decided_at"))
        decided_by = raw.get("decided_by")
        text = raw.get("summary") or raw.get("reason")
        if not (decision_id and decided_at and decided_by and text):
            continue
        matched.append({
            "raw": raw,
            "decision_id": decision_id,
            "decided_at": decided_at,
            "decided_by": decided_by,
            "text": text,
            "source_ids": _event_ids(raw.get("sources") or []),
            "work": str((raw.get("scope") or {}).get("work") or ""),
            "decision_entry": positions.get(f"r-dec-{decision_id}"),
            "applied": 0,
        })
    for answer in answers:
        if answer.get("basis") != "standing_rule":
            continue
        question = str(answer.get("question") or "")
        answer_sources = _event_ids(answer.get("sources") or [])
        answer_entry = positions.get(f"r-ans-{answer.get('id')}")
        for rule in matched:
            if rule["source_ids"]:
                if not rule["source_ids"] & answer_sources:
                    continue
            elif not (rule["work"] and _same_work(rule["work"], question)):
                continue
            # An answer never counts before the decision it rests on.
            if (answer_entry is not None and rule["decision_entry"] is not None
                    and answer_entry <= rule["decision_entry"]):
                continue
            # One answer counts once: the first matching rule owns it, so overlapping rules cannot double count.
            rule["applied"] += 1
            break
    return [m.StandingRule(
        id=str(rule["raw"].get("id") or f"rule-{rule['decision_id']}"), text=str(rule["text"]),
        scope=rule["raw"].get("scope") or {}, decision_id=rule["decision_id"],
        decided_by=str(rule["decided_by"]), decided_at=rule["decided_at"], applied_count=rule["applied"],
    ) for rule in matched]


def summary() -> m.Insights:
    project = store().get("project", "current") or {}
    record = _records()
    return m.Insights(
        generated_at=_generated_at(record),
        demo_data=bool(project.get("demo_data", True)),
        standing_rules=_standing_rules(record),
        patterns=_patterns(record),
    )
