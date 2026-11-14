"""Flags cover-up work that is planned, started or asked for before its required inspection is signed off.

The plan says which task needs which inspection (`Task.requires_inspection`). A sign-off counts when an
`inspection_passed` fact or a record entry says so. Everything here is plain code over the store.
"""
import re
from datetime import datetime, timezone

from app.core import models as m
from app.core.registry import area
from app.core.store import store

TRIGGERS = {"work_planned", "work_started", "question"}
SCHEDULING = {"inspection_scheduled", "inspection_moved"}
VERBS = {"work_planned": "plans to", "work_started": "started to", "question": "asks to"}
# Work that hides what an inspector has to see. Whole words, so "closet" or "dashboard" do not count.
COVER_UP = re.compile(
    r"\b(clos(e|es|ed|ing|ure)|drywall\w*|board(s|ing)?|insulat\w*|sheath\w*|ceilings?|backfill\w*"
    r"|cover(s|ed|ing)?|tap(e|ing)|hang(s|ing)?)\b"
)
SIGN_OFF_WORDS = ("passed", "signed off", "sign-off received")
INACTIVE = {"resolved", "dismissed"}


def evaluate(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.Flag]:
    plan = _plan()
    flags: dict[str, m.Flag] = {}
    for fact in facts:
        if fact.type == "inspection_passed":
            for flag in _resolve(event, fact):
                flags[flag.id] = flag
    for fact in facts:
        if fact.type not in TRIGGERS:
            continue
        for task in _tasks_for(fact, plan):
            flag = _raise(event, fact, task, plan, facts)
            if flag is not None and flag.id not in flags:
                flags[flag.id] = flag
    return list(flags.values())


def _plan() -> m.Plan:
    stored = store().get("plan", "current")
    return m.Plan.model_validate(stored) if stored else area("schedule").baseline()


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _unit(value: object) -> str:
    return re.sub(r"^unit\s+", "", _norm(value))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _is_cover_up(text: str) -> bool:
    return COVER_UP.search(text.lower()) is not None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _inspection_name(requires: str, unit: str) -> str:
    """'Rough plumbing 2A' names the inspection and the unit; drop the unit to get the inspection."""
    name = _norm(requires)
    unit = _norm(unit)
    if unit and name.endswith(" " + unit):
        name = name[: -len(unit) - 1]
    return name


def _matches_inspection(fact: dict, unit: str, requires: str) -> bool:
    data = fact.get("data") or {}
    if _unit(data.get("unit")) != _unit(unit):
        return False
    named = _norm(data.get("inspection"))
    return bool(named) and (named in _norm(requires) or _inspection_name(requires, unit) in named)


def _gated(plan: m.Plan, unit: str) -> list[m.Task]:
    return [t for t in plan.tasks if t.requires_inspection and _unit(t.unit) == unit]


def _tasks_for(fact: m.Fact, plan: m.Plan) -> list[m.Task]:
    unit = _unit(fact.data.get("unit"))
    if not unit:
        return []
    gated = _gated(plan, unit)
    named = _norm(fact.data.get("task"))
    by_id = [t for t in gated if named and _norm(t.id) == named]
    if by_id:
        return by_id
    text = " ".join(str(fact.data.get(k) or "") for k in ("task", "topic")).strip() or fact.subject
    if not _is_cover_up(text):
        return []
    return [t for t in gated if _is_cover_up(t.name)]


def _signed_off(task: m.Task, facts_now: list[m.Fact]) -> bool:
    unit, requires = task.unit or "", task.requires_inspection or ""
    known = [f.model_dump() for f in facts_now] + store().list("facts")
    if any(f.get("type") == "inspection_passed" and _matches_inspection(f, unit, requires) for f in known):
        return True
    name = _inspection_name(requires, unit)
    for entry in store().list("record"):
        title = _norm(entry.get("title"))
        if _unit((entry.get("refs") or {}).get("unit")) != _unit(unit) or name not in title:
            continue
        if any(word in title for word in SIGN_OFF_WORDS):
            return True
    return False


def _evidence(event: m.InboundEvent, quote: str | None) -> m.Evidence:
    text = quote or event.transcript or event.text or event.subject or ""
    return m.Evidence(event_id=event.id, channel=event.channel, sender=event.sender, at=event.sent_at, quote=text)


def _latest_schedule(task: m.Task) -> dict | None:
    unit, requires = task.unit or "", task.requires_inspection or ""
    found = [f for f in store().list("facts") if f.get("type") in SCHEDULING and _matches_inspection(f, unit, requires)]
    return found[-1] if found else None


def _flag_id(task: m.Task, plan: m.Plan) -> str:
    unit = _unit(task.unit)
    if len(_gated(plan, unit)) == 1:
        return f"f-seq-{_slug(unit)}"
    return f"f-seq-{_slug(unit)}-{_slug(task.id)}"


def _work_name(task: m.Task) -> str:
    """'Close walls 2B' names the work and the unit; drop the unit to compare work across units."""
    return _inspection_name(task.name, task.unit or "")


def _rule_scope(rule: dict, plan: m.Plan) -> dict | None:
    """The scope a standing rule covers. Rules stored without a scope fall back to the flag they were decided on."""
    if rule.get("scope"):
        return rule["scope"]
    flag = store().get("flags", rule.get("flag_id") or "")
    if not flag:
        return None
    affected = flag.get("affected") or {}
    task = next((t for t in plan.tasks if t.id == affected.get("task")), None)
    return {
        "flag_type": flag.get("type"),
        "inspection": _inspection_name(affected.get("inspection", ""), affected.get("unit", "")),
        "work": _work_name(task) if task else None,
    }


def _standing_rule_covers(task: m.Task, plan: m.Plan) -> bool:
    """A hold the superintendent marked for similar cases already decides this one; qa tells the crew, so no
    second flag asks the superintendent again."""
    inspection = _inspection_name(task.requires_inspection or "", task.unit or "")
    work = _work_name(task)
    for rule in store().list("rules"):
        if rule.get("status") == "superseded" or rule.get("action") != "hold_work":
            continue
        scope = _rule_scope(rule, plan)
        if not scope or scope.get("flag_type") != "out_of_sequence":
            continue
        if _norm(scope.get("inspection")) == inspection and (not scope.get("work") or _norm(scope["work"]) == work):
            return True
    return False


def _raise(event: m.InboundEvent, fact: m.Fact, task: m.Task, plan: m.Plan, facts: list[m.Fact]) -> m.Flag | None:
    flag_id = _flag_id(task, plan)
    # One incident, one flag: a repeated ask must not reopen a flag the superintendent already held or dismissed.
    if store().get("flags", flag_id) is not None or _signed_off(task, facts) or _standing_rule_covers(task, plan):
        return None

    evidence: list[m.Evidence] = []
    schedule = _latest_schedule(task)
    inspection_at = None
    if schedule is not None:
        data = schedule.get("data") or {}
        inspection_at = _time(data.get("new_time") or data.get("time"))
        stored = store().get("events", schedule.get("event_id", ""))
        if stored is not None and stored["id"] != event.id:
            evidence.append(_evidence(m.InboundEvent.model_validate(stored), schedule.get("quote")))
    evidence.append(_evidence(event, fact.quote))

    starts_at = _time(fact.data.get("start")) or _utc(task.start)
    early = inspection_at is None or starts_at is None or starts_at < inspection_at
    name = _inspection_name(task.requires_inspection or "", task.unit or "")
    work = _lower_first(task.name)
    quote = schedule.get("quote") if schedule else None
    when = f'Latest schedule update: "{quote}"' if quote else "No inspection date is in the record."
    return m.Flag(
        id=flag_id,
        type="out_of_sequence",
        severity="high" if early else "medium",
        title=f"{task.crew} {VERBS[fact.type]} {work} before the {name} inspection",
        summary=f"The {name} inspection for {task.unit} is not signed off. {when} Doing {work} first would hide the work the inspector has to see.",
        raised_at=event.received_at,
        work_starts_at=starts_at,
        affected={"unit": task.unit or "", "crew": task.crew, "task": task.id, "inspection": task.requires_inspection or ""},
        evidence=evidence,
    )


def _announce_hold_release(flag: m.Flag, event: m.InboundEvent) -> None:
    """A sign-off on a held flag keeps the hold; the record says why it can now be lifted."""
    inspection = _inspection_name(flag.affected.get("inspection", ""), flag.affected.get("unit", ""))
    unit = flag.affected.get("unit", "")
    entry_id = f"r-seq-hold-{flag.id}"
    store().put("record", entry_id, m.RecordEntry(
        id=entry_id, at=event.sent_at, kind="info",
        title=f"{inspection or 'The required inspection'} passed{'' if not unit else ' for ' + unit}. The hold can be released.",
        detail="The sign-off is on record. The superintendent still decides when the work may start.",
        actor="Aurora", source_event_ids=[event.id], refs={"flag": flag.id, "unit": unit},
    ))


def _resolve(event: m.InboundEvent, fact: m.Fact) -> list[m.Flag]:
    updated = []
    for stored in store().list("flags"):
        if stored.get("type") != "out_of_sequence" or stored.get("status") in INACTIVE:
            continue
        flag = m.Flag.model_validate(stored)
        requires = flag.affected.get("inspection", "")
        if not requires or not _matches_inspection(fact.model_dump(), flag.affected.get("unit", ""), requires):
            continue
        evidence = _evidence(event, fact.quote)
        if not any(item.event_id == evidence.event_id for item in flag.evidence):
            flag.evidence = [*flag.evidence, evidence]
        if flag.status == "held":
            # A human hold is not undone by an inspection: the crew may only start once the superintendent releases it.
            _announce_hold_release(flag, event)
        else:
            flag.status = "resolved"
        updated.append(flag)
    return updated
