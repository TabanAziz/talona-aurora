"""The four read-only tools, translated into GETs and one POST against the Aurora API.

Nothing here decides anything about the site: the tools pass the record through and let the start check answer.
The only judgement they make is safety: when the API does not answer, can_start says unknown, never yes, and the
three read tools say so instead of pretending the site is empty.
"""
from datetime import date, datetime, timedelta, timezone

import aurora

FLAG_STATES = ("open", "held")


def _day(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed).date()


def _task(task: dict) -> dict:
    return {key: task.get(key) for key in ("id", "name", "unit", "crew", "start", "status")}


def site_state() -> dict:
    """Project name, how many flags and waiting items are open, and the tasks planned for today and tomorrow."""
    try:
        project = aurora.get("/api/project") or {}
        flags = aurora.get("/api/flags") or []
        waiting = aurora.get("/api/waiting") or []
        plan = aurora.get("/api/plan") or {}
        events = aurora.get("/api/events") or []
    except aurora.Unreachable as error:
        return {"reachable": False, "error": str(error)}
    days = [day for day in (_day(event.get("received_at")) for event in events if isinstance(event, dict)) if day]
    day = max(days) if days else datetime.now(timezone.utc).date()
    tasks = [task for task in plan.get("tasks") or [] if isinstance(task, dict)]
    open_flags = [flag for flag in flags if isinstance(flag, dict) and flag.get("status") in FLAG_STATES]
    return {
        "reachable": True,
        "project": project.get("name"),
        "day": day.isoformat(),
        "open_flags": len(open_flags),
        "open_waiting": len(waiting),
        "today": [_task(task) for task in tasks if _day(task.get("start")) == day],
        "tomorrow": [_task(task) for task in tasks if _day(task.get("start")) == day + timedelta(days=1)],
    }


def open_flags() -> dict:
    """Every open or held flag: id, type, title, when the work starts, what it affects and its status."""
    try:
        flags = aurora.get("/api/flags") or []
    except aurora.Unreachable as error:
        return {"reachable": False, "error": str(error)}
    items = [
        {key: flag.get(key) for key in ("id", "type", "title", "work_starts_at", "affected", "status")}
        for flag in flags
        if isinstance(flag, dict) and flag.get("status") in FLAG_STATES
    ]
    return {"reachable": True, "count": len(items), "flags": items}


def waiting_on() -> dict:
    """Who owes what, since when and until when, with the events that opened it."""
    try:
        waiting = aurora.get("/api/waiting") or []
    except aurora.Unreachable as error:
        return {"reachable": False, "error": str(error)}
    items = [
        {key: item.get(key) for key in ("id", "on", "what", "since", "due", "source_event_ids")}
        for item in waiting
        if isinstance(item, dict)
    ]
    return {"reachable": True, "count": len(items), "items": items}


def _reason(raw: dict) -> dict:
    return {
        "kind": raw.get("kind"),
        "text": raw.get("text"),
        "blocking": raw.get("blocking"),
        "flag_id": raw.get("flag_id"),
        "sources": [source.get("event_id") for source in raw.get("sources") or [] if isinstance(source, dict)],
    }


def unknown_state(reason: str) -> dict:
    """The answer a robot must get when Aurora could not be asked: not allowed, and it says why."""
    return {
        "allowed": "unknown",
        "summary": "State unknown: Aurora could not be reached, so this start is not allowed.",
        "task_id": None,
        "unit": None,
        "reasons": [{"kind": "not_in_record", "text": f"State unknown: {reason}", "blocking": False,
                     "flag_id": None, "sources": []}],
    }


def can_start(asked_by: str, task_id: str | None = None, unit: str | None = None,
              activity: str | None = None) -> dict:
    """May this task start? The gate's verdict, its reasons in plain words and the event ids behind them."""
    try:
        check = aurora.post("/api/context/can-start", {"asked_by": asked_by, "task_id": task_id, "unit": unit,
                                                       "activity": activity})
    except aurora.Unreachable as error:
        return unknown_state(str(error))
    if not isinstance(check, dict) or "allowed" not in check:
        return unknown_state("the start check answered nothing usable")
    return {
        "allowed": check.get("allowed"),
        "summary": check.get("summary"),
        "task_id": check.get("task_id"),
        "unit": check.get("unit"),
        "activity": check.get("activity"),
        "checked_at": check.get("checked_at"),
        "reasons": [_reason(raw) for raw in check.get("reasons") or [] if isinstance(raw, dict)],
    }
