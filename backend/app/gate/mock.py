"""Mock: canned start checks per planned task, from mocks/scenario.json."""
import re
import uuid
from datetime import datetime, timezone

from app.core import models as m
from app.core import scenario
from app.core.registry import area
from app.core.store import store


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _plan() -> m.Plan:
    stored = store().get("plan", "current")
    return m.Plan.model_validate(stored) if stored else area("schedule").baseline()


def _task(request: m.StartCheckRequest) -> m.Task | None:
    """A task id wins. Otherwise the one planned task in the unit whose name fits the activity.

    A unit alone is not enough to know which task is meant, so it answers unknown instead of guessing.
    """
    tasks = _plan().tasks
    if request.task_id:
        return next((t for t in tasks if _norm(t.id) == _norm(request.task_id)), None)
    unit, activity = _norm(request.unit), _norm(request.activity)
    if not unit or not activity:
        return None
    fits = [t for t in tasks if _norm(t.unit) == unit and activity in _norm(t.name)]
    return fits[0] if len(fits) == 1 else None


def _at() -> datetime:
    """What the answer reasons about is the time of the latest event, never the wall clock."""
    times = [
        at for at in (_time(event.get("received_at")) for event in store().list("events")) if at is not None
    ]
    return max(times) if times else datetime.now(timezone.utc)


def check(request: m.StartCheckRequest) -> m.StartCheck:
    task = _task(request)
    canned = scenario.load()["start_checks"].get(task.id.lower()) if task else None
    asked = request.task_id or request.unit or "the task"
    # Agents and robots ask in parallel, so an id counted from the collection would collide and overwrite.
    check_id = f"chk-{uuid.uuid4().hex[:12]}"
    if canned is None:
        return m.StartCheck(
            id=check_id, asked_by=request.asked_by,
            task_id=task.id if task else request.task_id,
            unit=(task.unit if task else request.unit), activity=request.activity,
            allowed="unknown",
            summary=f"Aurora cannot answer for {asked} from the record. Ask the superintendent.",
            reasons=[m.StartReason(
                kind="not_in_record", text=f"The record holds nothing that answers for {asked}.", blocking=False,
            )],
            checked_at=_at(),
        )
    return m.StartCheck(
        id=check_id, asked_by=request.asked_by,
        task_id=canned.get("task_id") or (task.id if task else request.task_id),
        unit=canned.get("unit") or (task.unit if task else request.unit),
        activity=request.activity,
        allowed=canned["allowed"], summary=canned["summary"],
        reasons=[m.StartReason.model_validate(raw) for raw in canned.get("reasons", [])],
        checked_at=_at(),
    )
