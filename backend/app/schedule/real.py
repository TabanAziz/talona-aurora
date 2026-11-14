"""Schedule impact calculated from task dependencies (board decision: no model predicts schedule effects).

A deviation moves the task it hits, a forward pass over `depends_on` moves every task that would otherwise
start before its predecessors end, and the result becomes a proposal. Nothing changes the stored plan until
a human accepts the proposal and the caller stores what `apply` returns.
"""
from datetime import date, datetime, time, timedelta, timezone

from app import demodata
from app.core import models as m, site
from app.core.store import store

# Assumption shown to the superintendent in the proposal params, not a measured value.
MINUTES_PER_TRUCK = 45
# The handover is at 16:00 on the plan, so a task that would run past 16:00 moves to the next working day.
WORKDAY_END = time(16, 0)
SUMMARY_TASKS = 2
HOLD_TYPES = {"stale_drawing", "unacknowledged_change", "out_of_sequence"}


class PlanError(ValueError):
    """The plan or a proposal can not be used: unknown tasks, a dependency cycle, or an outdated proposal."""


class CyclicPlanError(PlanError):
    pass


def baseline() -> m.Plan:
    plan = demodata.load().plan
    order(plan)
    return plan


def propose(flag: m.Flag) -> m.Proposal | None:
    if flag.type in HOLD_TYPES:
        return _hold(flag)
    if flag.type == "plan_deviation":
        return _reschedule(flag, _current_plan())
    return None


def apply(proposal: m.Proposal) -> m.Plan:
    plan = _current_plan()
    if not proposal.shifts and proposal.handover_new is None:
        return plan
    tasks = {task.id: task for task in plan.tasks}
    for shift in proposal.shifts:
        task = tasks.get(shift.task_id)
        if task is None:
            raise PlanError(f"proposal {proposal.id} moves {shift.task_id}, which is not in the plan")
        if (task.start, task.end) != (shift.old_start, shift.old_end):
            raise PlanError(f"proposal {proposal.id} is out of date: {task.id} moved since it was calculated")
        task.start, task.end = shift.new_start, shift.new_end
    if proposal.handover_new is not None:
        plan.handover = proposal.handover_new
    for task in order(plan):
        for dep in task.depends_on:
            if tasks[dep].end > task.start:
                raise PlanError(f"applying {proposal.id} would start {task.id} before {dep} ends")
    return plan


def order(plan: m.Plan) -> list[m.Task]:
    """Tasks with every task after the tasks it depends on. Rejects unknown dependencies and cycles."""
    tasks = {task.id: task for task in plan.tasks}
    for task in plan.tasks:
        unknown = [dep for dep in task.depends_on if dep not in tasks]
        if unknown:
            raise PlanError(f"{task.id} depends on {', '.join(unknown)}, which is not in the plan")
    remaining = {task.id: len(set(task.depends_on)) for task in plan.tasks}
    successors = _successors(plan)
    ready = [task.id for task in plan.tasks if remaining[task.id] == 0]
    result: list[m.Task] = []
    while ready:
        task_id = ready.pop(0)
        result.append(tasks[task_id])
        for succ in successors[task_id]:
            remaining[succ] -= 1
            if remaining[succ] == 0:
                ready.append(succ)
    if len(result) < len(plan.tasks):
        stuck = sorted(task_id for task_id, count in remaining.items() if count > 0)
        raise CyclicPlanError(f"the plan has a dependency cycle among {', '.join(stuck)}")
    return result


def impact(plan: m.Plan, task_id: str, new_start: datetime, new_end: datetime) -> tuple[list[m.TaskShift], datetime]:
    """Shifts of every task that moves when `task_id` takes the new times, and the resulting handover."""
    ordered = order(plan)
    times = {task.id: (task.start, task.end) for task in plan.tasks}
    times[task_id] = (new_start, new_end)
    for task in ordered:
        if task.id == task_id or not task.depends_on:
            continue
        ready_at = max(times[dep][1] for dep in task.depends_on)
        start, end = times[task.id]
        if ready_at > start:
            times[task.id] = _move_after(start, end, ready_at)
    shifts = [
        m.TaskShift(
            task_id=task.id, name=task.name, crew=task.crew, old_start=task.start, old_end=task.end,
            new_start=times[task.id][0], new_end=times[task.id][1],
        )
        for task in ordered
        if times[task.id] != (task.start, task.end)
    ]
    return shifts, _handover(plan, shifts)


def add_working_days(moment: datetime, days: int) -> datetime:
    while days > 0:
        moment += timedelta(days=1)
        if _is_working_day(moment.date()):
            days -= 1
    return moment


def working_days_between(first: date, last: date) -> int:
    count, day = 0, first
    while day < last:
        day += timedelta(days=1)
        if _is_working_day(day):
            count += 1
    return count


def _is_working_day(day: date) -> bool:
    return day.weekday() < 5


def _move_after(start: datetime, end: datetime, ready_at: datetime) -> tuple[datetime, datetime]:
    """Earliest slot at or after `ready_at`: later the same day for a short task if it still fits, else whole working days."""
    duration = end - start
    if start.date() == end.date():
        candidate = _next_full_hour(ready_at)
        # The workday end is a site-time time of day, so it is compared against the candidate in site time.
        local = site.local(candidate)
        day_end = datetime.combine(local.date(), WORKDAY_END, tzinfo=site.zone()).astimezone(timezone.utc)
        if _is_working_day(local.date()) and candidate + duration <= day_end:
            return candidate, candidate + duration
    days = 1
    while add_working_days(start, days) < ready_at:
        days += 1
    return add_working_days(start, days), add_working_days(end, days)


def _next_full_hour(moment: datetime) -> datetime:
    """Crews start on the hour, so a predecessor ending at 9:45 lets the next task start at 10:00."""
    floor = moment.replace(minute=0, second=0, microsecond=0)
    return floor if floor == moment else floor + timedelta(hours=1)


def _handover(plan: m.Plan, shifts: list[m.TaskShift]) -> datetime:
    """The handover follows the last task of the plan: when the latest end moves N working days later, the handover
    moves N working days. A delay that stays within the time before the latest end moves nothing."""
    if not shifts or not plan.tasks:
        return plan.handover
    moved = {s.task_id: s.new_end for s in shifts}
    old_latest = max(t.end for t in plan.tasks)
    new_latest = max(moved.get(t.id, t.end) for t in plan.tasks)
    if new_latest <= old_latest:
        return plan.handover
    handover = add_working_days(plan.handover, working_days_between(old_latest.date(), new_latest.date()))
    while new_latest > handover:
        handover = add_working_days(handover, 1)
    return handover


def _successors(plan: m.Plan) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {task.id: [] for task in plan.tasks}
    for task in plan.tasks:
        for dep in set(task.depends_on):
            if dep in result:
                result[dep].append(task.id)
    return result


def _current_plan() -> m.Plan:
    raw = store().get("plan", "current")
    return m.Plan.model_validate(raw) if raw else baseline()


def _facts(flag: m.Flag, fact_type: str) -> list[dict]:
    """Facts of the given type from the events this flag cites, newest last."""
    event_ids = {e.event_id for e in flag.evidence}
    return [f for f in store().list("facts") if f["event_id"] in event_ids and f["type"] == fact_type]


def _as_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _reschedule(flag: m.Flag, plan: m.Plan) -> m.Proposal | None:
    tasks = {task.id: task for task in plan.tasks}
    root = tasks.get(flag.affected.get("task", ""))
    if root is None:
        return None
    order(plan)
    # The rule may name the resource line and dates on the flag; the cited facts win where both are present.
    line = next((r for r in plan.resources if r.id == flag.affected.get("resource")), None)
    equipment = _facts(flag, "equipment_actual")
    delivery = _facts(flag, "delivery_actual")
    if equipment or (line and line.kind == "equipment"):
        change = _equipment_late(root, {**flag.affected, **(equipment[-1]["data"] if equipment else {})}, line)
    elif delivery or (line and line.kind == "delivery"):
        data = {**flag.affected, **(delivery[-1]["data"] if delivery else {})}
        change = _delivery_changed(root, flag, data, line, plan)
    else:
        return None
    if change is None:
        return None
    new_start, new_end, cause, params = change
    shifts, handover_new = impact(plan, root.id, new_start, new_end)
    if not shifts:
        return None
    return m.Proposal(
        id=f"p-{flag.id}",
        flag_id=flag.id,
        action="reschedule",
        summary=_summary(cause, root.id, shifts, plan.handover, handover_new),
        params={"task": root.id, **params},
        shifts=shifts,
        handover_old=plan.handover,
        handover_new=handover_new,
        basis="calculated",
    )


def _equipment_late(root: m.Task, data: dict, line: m.ResourceLine | None):
    item = data.get("item") or (line.item if line else "equipment")
    arrives = _as_date(data.get("actual_date"))
    if arrives is None or arrives <= root.start.date():
        return None
    days = 1
    while add_working_days(root.start, days).date() < arrives:
        days += 1
    new_start, new_end = add_working_days(root.start, days), add_working_days(root.end, days)
    cause = f"The {item.lower()} arrives {_day(datetime.combine(arrives, time()))}, so {root.name} moves to {_day(new_start)}."
    return new_start, new_end, cause, {"equipment": item, "available_from": arrives.isoformat()}


def _delivery_changed(root: m.Task, flag: m.Flag, data: dict, line: m.ResourceLine | None, plan: m.Plan):
    numbers = flag.numbers or {}
    planned, actual = numbers.get("planned", data.get("planned")), numbers.get("actual", data.get("actual"))
    if line is None:
        line = next((r for r in plan.resources if r.kind == "delivery" and r.item == data.get("item")), None)
    arrives = _as_date(data.get("actual_date"))
    if arrives is not None and arrives > root.start.date():
        moved = _equipment_late(root, data, line)
        if moved is None:
            return None
        start, end, cause, params = moved
        extra = max(0, int(actual - planned)) if actual is not None and planned is not None and line and line.unit == "trucks" else 0
        if extra:
            end += timedelta(minutes=extra * MINUTES_PER_TRUCK)
            params.update(extra_trucks=extra, minutes_per_truck=MINUTES_PER_TRUCK)
            cause += f" Unloading adds {extra * MINUTES_PER_TRUCK} minutes at an assumed {MINUTES_PER_TRUCK} minutes per extra truck."
        return start, end, cause, {**params, "delivery": data.get("item") or (line.item if line else "delivery")}
    if planned is None or actual is None or line is None or line.unit != "trucks" or actual <= planned:
        return None
    extra = int(actual - planned)
    minutes = extra * MINUTES_PER_TRUCK
    cause = (
        f"Extend {root.name} by {minutes} minutes, {extra} more truck{'s' if extra > 1 else ''} "
        f"at an assumed {MINUTES_PER_TRUCK} minutes each."
    )
    params = {"extra_trucks": extra, "minutes_per_truck": MINUTES_PER_TRUCK}
    return root.start, root.end + timedelta(minutes=minutes), cause, params


def _summary(cause: str, root_id: str, shifts: list[m.TaskShift], old: datetime, new: datetime) -> str:
    parts = [cause]
    others = [s for s in shifts if s.task_id != root_id]
    # A long chain reads badly on the flag page; the shifts list keeps every task for the plan view.
    for shift in others[:SUMMARY_TASKS]:
        if site.local(shift.new_start).date() == site.local(shift.old_start).date():
            parts.append(f"{shift.name} starts at {site.local(shift.new_start):%H:%M} instead of "
                         f"{site.local(shift.old_start):%H:%M}.")
        else:
            parts.append(f"{shift.name} moves to {_day(shift.new_start)}.")
    if len(others) > SUMMARY_TASKS:
        rest = len(others) - SUMMARY_TASKS
        parts.append(f"{rest} later task{'s move' if rest > 1 else ' moves'} with them.")
    days = working_days_between(old.date(), new.date())
    if days:
        parts.append(f"Handover moves by {days} working day{'s' if days > 1 else ''} to {_day(new)}.")
    else:
        parts.append(f"Handover stays on {_day(old)}.")
    return " ".join(parts)


def _day(moment: datetime) -> str:
    local = site.local(moment)
    return f"{local:%a %b} {local.day}"


def _hold(flag: m.Flag) -> m.Proposal | None:
    plan = _current_plan()
    task = next((t for t in plan.tasks if t.id == flag.affected.get("task")), None)
    unit = flag.affected.get("unit") or (task.unit if task else None)
    if task is None and unit is None:
        return None
    crew = flag.affected.get("crew") or (task.crew if task else "")
    work = crew.removesuffix(" crew").lower() if crew.endswith(" crew") else (task.name if task else "the work")
    where = f"{work} in {unit}" if unit else work
    if flag.type == "out_of_sequence":
        inspection = flag.affected.get("inspection") or (task.requires_inspection if task else None)
        until = f"the {inspection} inspection is signed off" if inspection else "the required inspection is signed off"
    else:
        until = f"the crew confirms {_current_revision(flag.affected.get('sheet'))}"
    params = {key: value for key, value in (("task", task.id if task else None), ("unit", unit)) if value}
    if_not_held, consequence = _if_not_held(task, plan)
    params["if_not_held"] = if_not_held
    summary = f"Hold {where} until {until}."
    return m.Proposal(
        id=f"p-{flag.id}",
        flag_id=flag.id,
        action="hold_work",
        summary=f"{summary} {consequence}" if consequence else summary,
        params=params,
        basis="rule",
    )


REDO_ASSUMPTION = "The wrong work is found when the task ends, and the task is then done once more."


def _if_not_held(task: m.Task | None, plan: m.Plan) -> tuple[dict, str | None]:
    """What the hold avoids, from the same forward pass as a reschedule: the task is redone once right after it
    ends, and every task that depends on it waits for the second pass."""
    if task is None:
        keys = ["task_id", "task_name", "crew", "rework_hours", "moved_tasks", "handover_old", "handover_new", "assumption"]
        return {key: None for key in keys}, None
    _, redo_end = _move_after(task.start, task.end, task.end)
    shifts, handover_new = impact(plan, task.id, task.start, redo_end)
    moved = [
        {"task_id": s.task_id, "name": s.name, "old_start": _iso(s.old_start), "new_start": _iso(s.new_start)}
        for s in shifts
        if s.task_id != task.id
    ]
    hours = _working_hours(task)
    info = {
        "task_id": task.id,
        "task_name": task.name,
        "crew": task.crew,
        "rework_hours": hours,
        "moved_tasks": moved,
        "handover_old": _iso(plan.handover),
        "handover_new": _iso(handover_new),
        "assumption": REDO_ASSUMPTION,
    }
    rework = f"{task.name} is done twice" + (f" ({hours:g} working hours more)" if hours is not None else "")
    later = f"{len(moved)} later task{'s move' if len(moved) != 1 else ' moves'}"
    if handover_new != plan.handover:
        handover = f"the handover moves from {_day(plan.handover)} to {_day(handover_new)}"
    else:
        handover = f"the handover stays on {_day(plan.handover)}"
    return info, f"If the work goes ahead and has to be redone once: {rework}, {later} and {handover}."


def _working_hours(task: m.Task) -> float | None:
    """Hours of work in the task: the span on a one-day task, the daily span times the working days otherwise."""
    if task.start.date() == task.end.date():
        return (task.end - task.start).total_seconds() / 3600
    daily = (task.end.hour * 60 + task.end.minute - task.start.hour * 60 - task.start.minute) / 60
    if daily <= 0:
        return None
    return daily * (working_days_between(task.start.date(), task.end.date()) + 1)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current_revision(sheet: str | None) -> str:
    if not sheet:
        return "the current drawing"
    revisions = [
        f["data"]["revision"] for f in store().list("facts")
        if f["type"] == "drawing_revision" and f["data"].get("sheet") == sheet and f["data"].get("revision")
    ]
    return f"{sheet} Rev {revisions[-1]}" if revisions else f"the current revision of {sheet}"
