"""Keeps a decision marked for similar cases as a standing rule: what was decided, by whom, when, and where it applies."""
import logging
import re

from app.core import models as m
from app.core.store import store

log = logging.getLogger(__name__)


def on_decision(decision: m.Decision) -> None:
    if not decision.standing_rule:
        return
    # The decision has already run and the crews were told; a rule that can not be kept must not turn it into an error.
    try:
        _keep(decision)
    except Exception as error:
        log.error("learning: no standing rule kept for %s: %s", decision.id, type(error).__name__)


def _keep(decision: m.Decision) -> None:
    s = store()
    raw = s.get("flags", decision.flag_id)
    if raw is None:
        return
    flag = m.Flag.model_validate(raw)
    rule = {
        "id": f"rule-{decision.id}",
        "decision_id": decision.id,
        "flag_id": flag.id,
        "action": decision.action,
        "decided_by": decision.decided_by,
        "decided_at": decision.decided_at.isoformat(),
        "reason": decision.reason,
        "scope": _scope(flag),
        "decided_on": {key: value for key, value in flag.affected.items() if value},
        "numbers": flag.numbers,
        "summary": _summary(flag, decision),
        "sources": [e.model_dump(mode="json") for e in flag.evidence],
        "status": "active",
    }
    # A newer decision on the same kind of case replaces the older one, so a question gets one current answer.
    specific = "work" in rule["scope"] or "inspection" in rule["scope"]
    for other in s.list("rules") if specific else []:
        other_id = other.get("decision_id") or other.get("id")
        if other_id and other_id != decision.id and other.get("status", "active") == "active" and other.get("scope") == rule["scope"]:
            s.put("rules", other_id, {**other, "status": "superseded", "superseded_by": decision.id})
    s.put("rules", decision.id, rule)


def _scope(flag: m.Flag) -> dict:
    """The case without the unit it was decided on: the same flag type, the same kind of work, the same check."""
    scope: dict[str, str] = {"flag_type": flag.type, "units": "all"}
    task = _task(flag.affected.get("task", ""))
    unit = flag.affected.get("unit") or (task.unit if task else "") or ""
    if task is not None:
        scope["work"] = _without_unit(task.name, unit)
        scope["crew"] = task.crew
        if task.requires_inspection:
            scope["inspection"] = _without_unit(task.requires_inspection, unit)
    elif flag.affected.get("crew"):
        scope["crew"] = flag.affected["crew"]
    if flag.affected.get("inspection") and "inspection" not in scope:
        scope["inspection"] = _without_unit(flag.affected["inspection"], unit)
    for key in ("sheet", "item"):
        if flag.affected.get(key):
            scope[key] = flag.affected[key]
    return scope


def _summary(flag: m.Flag, decision: m.Decision) -> str:
    scope = _scope(flag)
    verb = {"hold_work": "Hold", "release_work": "Release", "reschedule": "Reschedule", "dismiss": "Do not flag"}.get(
        decision.action, decision.action.replace("_", " ").capitalize())
    work = scope.get("work", "the work")
    if "inspection" in scope:
        return f"{verb} {work.lower()} in every unit until the {scope['inspection'].lower()} is signed off."
    return f"{verb} {work.lower()} in similar cases, as decided for {flag.title}."


def _task(task_id: str) -> m.Task | None:
    raw = store().get("plan", "current")
    if not raw or not task_id:
        return None
    return next((t for t in m.Plan.model_validate(raw).tasks if t.id == task_id), None)


def _without_unit(text: str, unit: str) -> str:
    """'Close walls 2A' and 'Rough plumbing 2A' describe a kind of work once the unit is taken out."""
    if not unit:
        return text.strip()
    return re.sub(rf"\s*\b{re.escape(unit)}\b\s*", " ", text, flags=re.IGNORECASE).strip()
