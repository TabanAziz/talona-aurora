"""The start check: may I start this task? It answers yes, no or unknown from the record and never changes it.

Every reason comes out of what the record already holds: the flags raised for this task, an inspection the plan
requires that nothing signs off, a sheet that changed after the crew last confirmed a revision, a resource that
deviates from the plan, a dependency that runs late, and standing rules the superintendent decided for similar
cases. A check never holds, releases or reschedules anything, and it calls no model.

The time it reasons about is the time of the latest event in the store, not the wall clock, so a replay answers the
same way on every machine.
"""
import re
import unicodedata
import uuid
from datetime import datetime, timezone

from app.core import models as m
from app.core.registry import area
from app.core.store import store

# A flag the superintendent decided on no longer stands in the way. Releasing a drawing hold cannot start work
# nobody confirmed: the unconfirmed sheet keeps its own reason from the waiting list.
INACTIVE = {"resolved", "dismissed", "released"}
CONFIRMATION = re.compile(r"^Confirm (?P<sheet>.+) Rev (?P<revision>\S+)$")
SIGN_OFF_WORDS = ("passed", "signed off", "sign-off received", "inspection passed")
# The flag types that answer one reason each, in the order a blocked task should read them.
FLAG_REASONS = {
    "out_of_sequence": ("inspection_open", True),
    "stale_drawing": ("superseded_drawing", True),
    "unacknowledged_change": ("drawing_not_confirmed", False),
    "plan_deviation": ("resource_deviation", False),
}
REASON_ORDER = ["work_on_hold", "superseded_drawing", "inspection_open", "unit_occupied", "drawing_not_confirmed",
                "resource_deviation", "dependency_open", "not_in_record"]
ASKER_MAX = 80
# Control characters and the Unicode line and paragraph separators break a record title or a mail line in two.
# str.isprintable would also refuse a no-break space or a soft hyphen pasted from a name, which harm nothing.
ASKER_REFUSED = {"Cc", "Zl", "Zp"}


def asker_problem(asked_by: str) -> str | None:
    """Why this name cannot ask, or None. The name goes into the record and the daily report as it is."""
    name = asked_by.strip()
    if not name:
        return "asked_by is empty. Send a short name, for example drywall-robot-1."
    if len(name) > ASKER_MAX:
        return f"asked_by is {len(name)} characters long. Send a name of at most {ASKER_MAX} characters."
    if any(unicodedata.category(char) in ASKER_REFUSED for char in asked_by):
        return "asked_by holds a control character or a line break. Send a name on one line."
    return None


def check(request: m.StartCheckRequest) -> m.StartCheck:
    """Answer for one task (or one unit plus activity) without changing any part of the record."""
    problem = asker_problem(request.asked_by)
    if problem is not None:
        raise ValueError(problem)
    plan = _plan()
    now = _at()
    task = _task(request, plan)
    if task is None:
        return _answer(request, None, [_not_in_record(request, plan)], now)
    reasons = _reasons(task, plan, request.asked_by)
    reasons.extend(_occupied_unit(request.asked_by, task, plan, now))
    return _answer(request, task, reasons, now)


def _answer(request: m.StartCheckRequest, task: m.Task | None, reasons: list[m.StartReason],
            now: datetime) -> m.StartCheck:
    ordered = [reason for kind in REASON_ORDER for reason in reasons if reason.kind == kind]
    if any(reason.kind == "not_in_record" for reason in ordered):
        allowed = "unknown"
    elif ordered:
        allowed = "no"
    else:
        allowed = "yes"
    asked = request.task_id or request.unit or "the task"
    name = task.name if task is not None else asked
    blocking = [reason for reason in ordered if reason.blocking]
    if allowed == "yes":
        summary = f"Nothing in the record stands in the way of {name}. You may start."
    elif allowed == "unknown":
        summary = ordered[0].text
    else:
        summary = (blocking[0].text if blocking else ordered[0].text)
    return m.StartCheck(
        id=f"chk-{uuid.uuid4().hex[:12]}", asked_by=request.asked_by,
        task_id=task.id if task is not None else request.task_id,
        unit=(task.unit if task is not None else request.unit) or None,
        activity=request.activity,
        allowed=allowed, summary=summary, reasons=ordered, checked_at=now,
    )


def _reasons(task: m.Task, plan: m.Plan, asked_by: str = "") -> list[m.StartReason]:
    """Every reason that applies, one per kind, the most serious first. A machine's own reasons come first, so
    the machine reads why it may not start rather than why the crew may not."""
    found: dict[str, m.StartReason] = {}
    for reason in (_for_machine(task, asked_by) + list(_from_flags(task)) + _from_plan(task, plan)
                   + _from_rules(task, plan)):
        found.setdefault(reason.kind, reason)
    return list(found.values())


def _for_machine(task: m.Task, asked_by: str) -> list[m.StartReason]:
    """A registered machine that has not confirmed the current revision of a sheet covering this unit. Naming an
    outdated revision is worse than silence: the machine holds old geometry, so that reason blocks."""
    name = asked_by.strip()
    if not name or name not in {machine.id for machine in area("machine").machines()}:
        return []
    for item in store().list("waiting"):
        match = CONFIRMATION.match(item.get("what") or "")
        if item.get("status") != "open" or item.get("on") != name or match is None:
            continue
        sheet, revision = match["sheet"], match["revision"]
        fact = _revision_fact(sheet, revision)
        if fact is None or task.unit not in [str(unit) for unit in (fact.get("data") or {}).get("units") or []]:
            continue
        latest = getattr(area("record"), "current_revision", lambda name: None)(sheet)
        if latest is not None and latest.id != fact.get("id"):
            continue
        sources = [_evidence(fact.get("event_id"), fact.get("quote"))]
        loaded = _loaded_instead(name, sheet, revision, item)
        if loaded is not None:
            sources.append(_evidence(loaded.get("event_id"), loaded.get("quote")))
            text = (f"{name} loaded {sheet} Rev {(loaded.get('data') or {}).get('revision')}, but Rev {revision} is "
                    f"current and changed a drawing that covers {task.unit}. Load Rev {revision} and confirm it "
                    f"before starting.")
            return [m.StartReason(kind="superseded_drawing", text=text, blocking=True,
                                  sources=[source for source in sources if source is not None])]
        text = (f"{sheet} Rev {revision} changed a drawing that covers {task.unit} and {name} has not confirmed it. "
                f"Load Rev {revision} and confirm it before starting.")
        return [m.StartReason(kind="drawing_not_confirmed", text=text, blocking=False,
                              sources=[source for source in sources if source is not None])]
    # With its item closed, the machine can still load an older revision afterwards; its latest load is what it holds.
    for sheet, loaded in _latest_loads(name).items():
        latest = getattr(area("record"), "current_revision", lambda name: None)(sheet)
        if latest is None:
            continue
        current = str(latest.data.get("revision") or "")
        if not current or (loaded.get("data") or {}).get("revision") == current:
            continue
        if task.unit not in [str(unit) for unit in latest.data.get("units") or []]:
            continue
        sources = [_evidence(latest.event_id, latest.quote), _evidence(loaded.get("event_id"), loaded.get("quote"))]
        text = (f"{name} loaded {sheet} Rev {(loaded.get('data') or {}).get('revision')}, but Rev {current} is "
                f"current and changed a drawing that covers {task.unit}. Load Rev {current} and confirm it "
                f"before starting.")
        return [m.StartReason(kind="superseded_drawing", text=text, blocking=True,
                              sources=[source for source in sources if source is not None])]
    return []


def _latest_loads(name: str) -> dict[str, dict]:
    """The last revision this machine confirmed per sheet, in the order the confirmations were stored."""
    loads: dict[str, dict] = {}
    for fact in store().list("facts"):
        data = fact.get("data") or {}
        if fact.get("type") == "acknowledgement" and data.get("crew") == name and data.get("sheet"):
            loads[str(data["sheet"])] = fact
    return loads


def _loaded_instead(name: str, sheet: str, revision: str, item: dict) -> dict | None:
    """The machine's latest confirmation of another revision of this sheet since it was asked to confirm."""
    since = _time(item.get("since"))
    for fact in reversed(store().list("facts")):
        data = fact.get("data") or {}
        if fact.get("type") != "acknowledgement" or data.get("crew") != name or data.get("sheet") != sheet:
            continue
        event = store().get("events", fact.get("event_id") or "") or {}
        at = _time(event.get("received_at"))
        if since is not None and (at is None or at < since):
            continue
        return fact if data.get("revision") != revision else None
    return None


def _from_flags(task: m.Task) -> list[m.StartReason]:
    reasons = []
    for raw in store().list("flags"):
        if raw.get("status") in INACTIVE or not _for_task(raw, task):
            continue
        flag = m.Flag.model_validate(raw)
        if flag.status == "held":
            reasons.append(_from_flag("work_on_hold", flag, True,
                                      f"{flag.title}: the superintendent held this work until they release it."))
            continue
        kind, blocking = FLAG_REASONS.get(flag.type, (None, False))
        if kind is None:
            continue
        if kind == "resource_deviation" and _covered(flag.id):
            continue
        if kind == "resource_deviation":
            missing = ("Accept the calculated plan change before work starts." if flag.proposal_id
                       else "No accepted plan change covers it yet; the superintendent has to decide.")
            text = f"{flag.title}. {missing}"
        else:
            text = flag.summary
        reasons.append(_from_flag(kind, flag, blocking, text))
    return reasons


def _from_plan(task: m.Task, plan: m.Plan) -> list[m.StartReason]:
    """What the plan and the record say without a flag: an unsigned inspection, an unconfirmed sheet, a late
    dependency."""
    reasons = []
    if task.requires_inspection and not _signed_off(task):
        reasons.append(_inspection_reason(task))
    unconfirmed = _unconfirmed(task)
    if unconfirmed is not None:
        reasons.append(unconfirmed)
    reasons.extend(_late_dependencies(task, plan))
    return reasons


def _occupied_unit(asked_by: str, task: m.Task, plan: m.Plan, now: datetime) -> list[m.StartReason]:
    """A crew keeps a machine out of a unit once the crew reported its start there, not while the plan only
    places the crew in it.

    The layout robot chalks the lines the framers then build on, so it may prepare a unit they are planned to
    work in. A planned task alone therefore does not block; a reported start, one the record can be cited for,
    does."""
    if store().get("machines", asked_by.strip()) is None or not task.unit:
        return []
    texts, sources = [], []
    for other in plan.tasks:
        if (_norm(other.unit) != _norm(task.unit) or not other.crew.strip()
                or store().get("machines", other.crew) is not None or other.status == "done"
                or not other.start <= now < other.end):
            continue
        started = _started_work(other)
        if not started:
            continue
        texts.append(f"{other.crew} reported work started in {other.unit} on {other.name} ({other.id}), planned "
                     f"from {other.start:%a %d %b %H:%M %Z} to {other.end:%a %d %b %H:%M %Z}.")
        sources.extend(source for source in
                       (_evidence(fact.get("event_id"), fact.get("quote")) for fact in started)
                       if source is not None)
    if not texts:
        return []
    return [m.StartReason(kind="unit_occupied", text=" ".join(texts), blocking=True, sources=sources)]


def _started_work(task: m.Task) -> list[dict]:
    """The record entries that report this crew task started, by task id or by its unit and crew."""
    started = []
    for fact in store().list("facts"):
        if fact.get("type") != "work_started":
            continue
        data = fact.get("data") or {}
        same_task = _norm(data.get("task")) == _norm(task.id)
        same_unit_crew = (_norm(data.get("unit")) == _norm(task.unit)
                          and _norm(data.get("crew")) == _norm(task.crew))
        if same_task or same_unit_crew:
            started.append(fact)
    return started


def _from_rules(task: m.Task, plan: m.Plan) -> list[m.StartReason]:
    """A standing rule for similar work is a hold the superintendent already decided."""
    for rule in store().list("rules"):
        if rule.get("status") == "superseded" or rule.get("action") != "hold_work":
            continue
        if not _rule_covers(rule, task, plan):
            continue
        # Inspection rules hold similar work only until its required sign-off exists.
        if (rule.get("scope") or {}).get("inspection") and task.requires_inspection and _signed_off(task):
            continue
        sources = [_evidence(item.get("event_id"), item.get("quote")) for item in rule.get("sources") or []]
        text = (f"A standing rule from {rule.get('decided_by') or 'the superintendent'} holds work like "
                f"{task.name}: {rule.get('reason') or rule.get('summary') or 'the same case was held before'}.")
        return [m.StartReason(kind="work_on_hold", text=text, blocking=True,
                              sources=[source for source in sources if source is not None],
                              flag_id=rule.get("flag_id"))]
    return []


def _rule_covers(rule: dict, task: m.Task, plan: m.Plan) -> bool:
    scope = rule.get("scope") or {}
    if scope.get("flag_type") not in (None, "out_of_sequence"):
        return False
    inspection = _inspection_name(task.requires_inspection or "", task.unit or "")
    if scope.get("inspection") and _norm(scope["inspection"]) != inspection:
        return False
    if not scope.get("inspection") and not scope.get("work"):
        return False
    work = _work_name(task)
    return not scope.get("work") or _norm(scope["work"]) == work


def _from_flag(kind: str, flag: m.Flag, blocking: bool, text: str) -> m.StartReason:
    return m.StartReason(kind=kind, text=text, blocking=blocking, sources=list(flag.evidence), flag_id=flag.id)


def _inspection_reason(task: m.Task) -> m.StartReason:
    name = _inspection_name(task.requires_inspection or "", task.unit or "")
    sources = []
    for fact in reversed(store().list("facts")):
        if fact.get("type") in {"inspection_scheduled", "inspection_moved"} and _matches_inspection(
                fact, task.unit or "", task.requires_inspection or ""):
            sources = [_evidence(fact.get("event_id"), fact.get("quote"))]
            break
    text = (f"The {name} inspection for {task.unit} is not signed off, so {_lower_first(task.name)} must wait.")
    return m.StartReason(kind="inspection_open", text=text, blocking=True,
                         sources=[source for source in sources if source is not None])


def _unconfirmed(task: m.Task) -> m.StartReason | None:
    """A sheet that covers this unit changed and this crew has not confirmed the newest revision."""
    for item in store().list("waiting"):
        match = CONFIRMATION.match(item.get("what") or "")
        if item.get("status") != "open" or item.get("on") != task.crew or match is None:
            continue
        sheet, revision = match["sheet"], match["revision"]
        fact = _revision_fact(sheet, revision)
        if fact is None or task.unit not in [str(unit) for unit in (fact.get("data") or {}).get("units") or []]:
            continue
        latest = getattr(area("record"), "current_revision", lambda name: None)(sheet)
        if latest is not None and latest.id != fact.get("id"):
            continue
        sources = [_evidence(fact.get("event_id"), fact.get("quote"))]
        if item.get("source_event_ids"):
            sources.append(_evidence(item["source_event_ids"][0], None))
        text = (f"{sheet} Rev {revision} changed a drawing that covers {task.unit} and {task.crew} has not confirmed "
                f"it. Ask the crew to confirm before it starts.")
        return m.StartReason(kind="drawing_not_confirmed", text=text, blocking=False,
                             sources=[source for source in sources if source is not None])
    return None


def _late_dependencies(task: m.Task, plan: m.Plan) -> list[m.StartReason]:
    reasons = []
    tasks = {other.id: other for other in plan.tasks}
    for dependency in task.depends_on:
        other = tasks.get(dependency)
        if other is None or other.status == "done" or other.end <= task.start:
            continue
        sources = [_evidence(fact.get("event_id"), fact.get("quote")) for fact in store().list("facts")
                   if _norm((fact.get("data") or {}).get("task")) == _norm(other.id)]
        text = (f"{other.name} ({other.id}) is not done and is planned to end {other.end:%a %d %b %H:%M}, after "
                f"{task.name} starts. Its own work has to be finished first.")
        reasons.append(m.StartReason(kind="dependency_open", text=text, blocking=False,
                                     sources=[source for source in sources if source is not None]))
    return reasons


def _covered(flag_id: str) -> bool:
    """An accepted plan change decides how the deviation is handled, so it no longer stands in the way."""
    return any(decision.get("flag_id") == flag_id and decision.get("action") == "reschedule"
               for decision in store().list("decisions"))


def _revision_fact(sheet: str, revision: str) -> dict | None:
    for fact in reversed(store().list("facts")):
        data = fact.get("data") or {}
        if fact.get("type") == "drawing_revision" and _norm(data.get("sheet")) == _norm(sheet) \
                and _norm(data.get("revision")) == _norm(revision):
            return fact
    return None


def _signed_off(task: m.Task) -> bool:
    """A pass counts when a fact or a record entry says the required inspection was passed."""
    unit, requires = task.unit or "", task.requires_inspection or ""
    if any(fact.get("type") == "inspection_passed" and _matches_inspection(fact, unit, requires)
           for fact in store().list("facts")):
        return True
    name = _inspection_name(requires, unit)
    for entry in store().list("record"):
        title = _norm(entry.get("title"))
        if _norm((entry.get("refs") or {}).get("unit")) != _norm(unit) or name not in title:
            continue
        if any(word in title for word in SIGN_OFF_WORDS):
            return True
    return False


def _for_task(raw: dict, task: m.Task) -> bool:
    """A flag stands in the way of its task, or of a unit it names without naming a task."""
    affected = raw.get("affected") or {}
    flag_task = _norm(affected.get("task"))
    if flag_task:
        return flag_task == _norm(task.id)
    flag_unit = _norm(affected.get("unit"))
    return bool(flag_unit) and flag_unit == _norm(task.unit)


def _task(request: m.StartCheckRequest, plan: m.Plan) -> m.Task | None:
    """A task id wins. Otherwise the one planned task in the unit whose name fits the activity."""
    if request.task_id:
        return next((task for task in plan.tasks if _norm(task.id) == _norm(request.task_id)), None)
    unit, activity = _norm(request.unit), _norm(request.activity)
    if not unit or not activity:
        return None
    fits = [task for task in plan.tasks if _norm(task.unit) == unit and activity in _norm(task.name)]
    return fits[0] if len(fits) == 1 else None


def _not_in_record(request: m.StartCheckRequest, plan: m.Plan) -> m.StartReason:
    if request.task_id:
        asked = request.task_id
        text = f"The plan holds no task {asked}, so Aurora cannot answer for it. Ask the superintendent."
    elif request.unit and request.activity:
        text = (f"The plan holds no single task for {request.activity} in {request.unit}, so Aurora cannot answer "
                f"for it. Ask the superintendent.")
    elif request.unit:
        text = (f"{request.unit} alone names no task. Ask with a task id, or with the unit and what is to be done.")
    else:
        text = "The question names no task or unit, so Aurora cannot answer it. Ask with a task id."
    return m.StartReason(kind="not_in_record", text=text, blocking=False)


def _plan() -> m.Plan:
    stored = store().get("plan", "current")
    return m.Plan.model_validate(stored) if stored else area("schedule").baseline()


def _at() -> datetime:
    """The time the answer reasons about is the latest event, or the latest record entry before one arrived.

    It never reads the wall clock, so a replay or a test gets the same answer on every machine.
    """
    times = [moment for moment in (_time(event.get("received_at")) for event in store().list("events"))
             if moment is not None]
    if times:
        return max(times)
    recorded = [moment for moment in (_time(entry.get("at")) for entry in store().list("record"))
                if moment is not None]
    if recorded:
        return max(recorded)
    # A store with neither an event nor a record has no time of its own; the epoch keeps the answer reproducible.
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _evidence(event_id: str | None, quote: str | None) -> m.Evidence | None:
    if not event_id:
        return None
    raw = store().get("events", event_id)
    if raw is None:
        return None
    event = m.InboundEvent.model_validate(raw)
    text = quote or event.transcript or event.text or event.subject or ""
    return m.Evidence(event_id=event.id, channel=event.channel, sender=event.sender, at=event.sent_at, quote=text)


def _matches_inspection(fact: dict, unit: str, requires: str) -> bool:
    data = fact.get("data") or {}
    if _norm(data.get("unit")) != _norm(unit):
        return False
    named = _norm(data.get("inspection"))
    return bool(named) and (named in _norm(requires) or _inspection_name(requires, unit) in named)


def _inspection_name(requires: str, unit: str) -> str:
    """'Rough plumbing 2A' names the inspection and the unit; drop the unit to get the inspection."""
    name = _norm(requires)
    suffix = _norm(unit)
    if suffix and name.endswith(" " + suffix):
        name = name[: -len(suffix) - 1]
    return name


def _work_name(task: m.Task) -> str:
    return _inspection_name(task.name, task.unit or "")


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment
