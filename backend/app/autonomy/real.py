"""Earned autonomy: the right to hold one kind of case alone, earned from three matching decisions.

The record is the only source of truth. A suggestion and its evidence are read back from the decisions, and a
hold Aurora makes by itself is a normal decision under the authorization id, through the same pipeline path a
human hold takes. Nothing else is automatic.
"""
import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from app.core import models as m, pipeline, scenario
from app.core.registry import area
from app.core.store import store
from app.live import delivery

log = logging.getLogger(__name__)

COLLECTION = "authorizations"
DAILY_LIMIT = 5
MIN_EVIDENCE_CONFIDENCE = 0.85
WINDOW_DAYS = 90
ACTIONS = ("hold_work", "release_work", "reschedule", "dismiss")
AURORA = "Aurora"


def _time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _now() -> datetime:
    """The record's clock: the newest event, else the newest record entry, never the wall clock."""
    events = [moment for moment in (_time(event.get("received_at")) for event in store().list("events"))
              if moment is not None]
    if events:
        return max(events)
    recorded = [moment for moment in (_time(entry.get("at")) for entry in store().list("record"))
                if moment is not None]
    if recorded:
        return max(recorded)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _plan() -> m.Plan:
    stored = store().get("plan", "current")
    return m.Plan.model_validate(stored) if stored else area("schedule").baseline()


def _task(task_id: str) -> m.Task | None:
    if not task_id:
        return None
    return next((task for task in _plan().tasks if task.id == task_id), None)


def _without_unit(text: str, unit: str) -> str:
    """'Close walls 2A' and 'Rough plumbing 2A' describe a kind of work once the unit is taken out."""
    if not unit:
        return text.strip()
    return re.sub(rf"\s*\b{re.escape(unit)}\b\s*", " ", text, flags=re.IGNORECASE).strip()


def _scope(flag: m.Flag) -> dict[str, str]:
    """The case without the unit: the same dict the learning area writes into a standing rule."""
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


def _statement(scope: dict[str, str], flag: m.Flag) -> str:
    """The same wording as the learning area's summary for the hold that earned the rule."""
    work = scope.get("work", "the work")
    if "inspection" in scope:
        return f"Hold {work.lower()} in every unit until the {scope['inspection'].lower()} is signed off."
    return f"Hold {work.lower()} in similar cases, as decided for {flag.title}."


def _digest(action: str, scope: dict[str, str], evidence: list[str]) -> str:
    return hashlib.sha256(json.dumps([action, scope, evidence], sort_keys=True).encode()).hexdigest()[:12]


def _decision_scope(decision: dict) -> dict[str, str] | None:
    raw = store().get("flags", decision.get("flag_id"))
    return _scope(m.Flag.model_validate(raw)) if raw else None


def _rule(rule_id: str) -> dict | None:
    for raw in store().list("rules"):
        if raw.get("id") == rule_id or f"rule-{raw.get('decision_id')}" == rule_id:
            return raw
    return None


def _end(authorization: m.Authorization) -> datetime | None:
    if authorization.revoked_at is not None:
        return authorization.revoked_at
    if authorization.superseded_by:
        replacing = store().get("decisions", authorization.superseded_by)
        return _time(replacing.get("decided_at")) if replacing else None
    return None


def _last_end(scope: dict[str, str]) -> datetime | None:
    ends = []
    for raw in store().list(COLLECTION):
        authorization = m.Authorization.model_validate(raw)
        if authorization.scope != scope:
            continue
        end = _end(authorization)
        if end is not None:
            ends.append(end)
    return max(ends) if ends else None


def _refresh_superseded() -> None:
    """A grant whose standing rule was replaced stops applying, the way the rule does."""
    for raw in store().list(COLLECTION):
        if raw.get("status", "active") != "active":
            continue
        authorization = m.Authorization.model_validate(raw)
        rule = _rule(authorization.rule_id)
        if rule is None or rule.get("status", "active") == "active":
            continue
        replacing = rule.get("superseded_by") or rule.get("decision_id")
        store().put(COLLECTION, authorization.id, authorization.model_copy(
            update={"status": "superseded", "superseded_by": replacing},
        ))


def _suggestion(scope: dict[str, str], decisions: list[dict]) -> m.AutonomySuggestion | None:
    now = _now()
    floor = now - timedelta(days=WINDOW_DAYS)
    end = _last_end(scope)
    relevant = []
    for decision in decisions:
        at = _time(decision.get("decided_at"))
        if at is None or at < floor:
            continue
        if end is not None and at <= end:
            continue
        relevant.append((decision, at))
    relevant.sort(key=lambda pair: pair[1])
    differing = [at for decision, at in relevant if decision.get("action") != "hold_work"]
    if differing:
        boundary = max(differing)
        relevant = [(decision, at) for decision, at in relevant if at > boundary]
    if len(relevant) < 3:
        return None
    last = relevant[-3:]
    if any(decision.get("action") != "hold_work" or decision.get("decided_by") == AURORA
           for decision, _ in last):
        return None
    evidence_decisions = [decision["id"] for decision, _ in last]
    evidence_flags = [decision["flag_id"] for decision, _ in last]
    raw = store().get("flags", evidence_flags[-1])
    if raw is None:
        return None
    flag = m.Flag.model_validate(raw)
    return m.AutonomySuggestion(
        id=f"sug-{_digest('hold_work', scope, evidence_decisions)}",
        action="hold_work", flag_type=scope.get("flag_type", flag.type), scope=scope,
        statement=_statement(scope, flag), evidence_decision_ids=evidence_decisions,
        evidence_flag_ids=evidence_flags, last_decided_at=last[-1][1],
    )


def _suggestions() -> list[m.AutonomySuggestion]:
    _refresh_superseded()
    groups: dict[str, tuple[dict[str, str], list[dict]]] = {}
    for decision in store().list("decisions"):
        if decision.get("decided_by") in (None, "", AURORA) or decision.get("action") not in ACTIONS:
            continue
        scope = _decision_scope(decision)
        if scope is None:
            continue
        key = json.dumps(scope, sort_keys=True)
        groups.setdefault(key, (scope, []))[1].append(decision)
    stored = store().list(COLLECTION)
    suggestions = []
    for scope, decisions in groups.values():
        if any(raw.get("scope") == scope and raw.get("status", "active") == "active" for raw in stored):
            continue
        suggestion = _suggestion(scope, decisions)
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


def _applications(authorization_id: str) -> list[m.AuthorizationApplication]:
    found = [decision for decision in store().list("decisions")
             if decision.get("authorization_id") == authorization_id]
    found.sort(key=lambda decision: _time(decision.get("decided_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc))
    return [m.AuthorizationApplication(
        decision_id=decision["id"], flag_id=decision["flag_id"],
        record_entry_id=f"r-dec-{decision['id']}", at=_time(decision["decided_at"]),
    ) for decision in found]


def _authorization(raw: dict) -> m.Authorization:
    authorization = m.Authorization.model_validate(raw)
    authorization.applications = _applications(authorization.id)
    return authorization


def _authorizations() -> list[m.Authorization]:
    _refresh_superseded()
    found = [_authorization(raw) for raw in store().list(COLLECTION)]
    found.sort(key=lambda authorization: (authorization.status != "active",
                                          -(_end(authorization) or authorization.granted_at).timestamp()))
    return found


def _holds_today(day: date) -> int:
    """Count automatic holds on the record day of the flag they held, not the wall date of the decision."""
    count = 0
    for decision in store().list("decisions"):
        if not decision.get("authorization_id"):
            continue
        flag = store().get("flags", decision.get("flag_id"))
        raised = _time(flag.get("raised_at")) if flag else None
        if raised is not None and raised.date() == day:
            count += 1
    return count


def _demo() -> tuple[list[m.AutonomySuggestion], list[m.Authorization]]:
    """The prepared demo suggestion and authorization, so the page has something to show before a grant."""
    project = store().get("project", "current") or {}
    if not project.get("demo_data"):
        return [], []
    canned = scenario.load().get("autonomy") or {}
    suggestions = [m.AutonomySuggestion.model_validate(raw) for raw in canned.get("suggestions") or []]
    authorizations = []
    for raw in canned.get("authorizations") or []:
        authorization = m.Authorization.model_validate(raw)
        authorization.applications = _applications(authorization.id)
        authorizations.append(authorization)
    return suggestions, authorizations


def suggest() -> m.Autonomy:
    now = _now()
    demo_suggestions, demo_authorizations = _demo()
    by_id = {authorization.id: authorization for authorization in demo_authorizations}
    for authorization in _authorizations():
        by_id[authorization.id] = authorization
    authorizations = sorted(by_id.values(), key=lambda authorization: (
        authorization.status != "active", -(_end(authorization) or authorization.granted_at).timestamp()))
    active = [authorization for authorization in authorizations if authorization.status == "active"]
    suggestions = []
    for suggestion in _suggestions() + demo_suggestions:
        if any(authorization.action == suggestion.action and authorization.scope == suggestion.scope
               for authorization in active):
            continue
        suggestions.append(suggestion)
    return m.Autonomy(
        generated_at=now, suggestions=suggestions, authorizations=authorizations,
        automatic_holds_today=_holds_today(now.date()), daily_limit=DAILY_LIMIT,
    )


def grant(request: m.AutonomyGrantRequest) -> m.Authorization:
    granted_by = request.granted_by.strip()
    if not granted_by:
        raise ValueError("A grant needs the name of the person granting it.")
    if request.suggestion_id.startswith("sug-") and len(request.suggestion_id) == 16:
        # A double click must return the same authorization, even though the active grant now hides the
        # suggestion that earned it.
        existing = store().get(COLLECTION, f"auth-{request.suggestion_id[4:]}")
        if existing is not None:
            return _authorization(existing)
    suggestion = next((item for item in _suggestions() if item.id == request.suggestion_id), None)
    if suggestion is None:
        if request.suggestion_id.startswith("sug-") and len(request.suggestion_id) == 16:
            raise ValueError("That suggestion is not supported by the record any more. Nothing was granted.")
        raise KeyError(request.suggestion_id)
    if suggestion.action != "hold_work":
        raise ValueError("Only holding work can be authorized. Releasing, rescheduling and dismissing always "
                         "stay with you.")
    authorization_id = f"auth-{_digest(suggestion.action, suggestion.scope, suggestion.evidence_decision_ids)}"
    existing = store().get(COLLECTION, authorization_id)
    if existing is not None:
        return _authorization(existing)
    authorization = m.Authorization(
        id=authorization_id, action=suggestion.action, flag_type=suggestion.flag_type, scope=suggestion.scope,
        statement=suggestion.statement, rule_id=f"rule-{suggestion.evidence_decision_ids[-1]}",
        evidence_decision_ids=suggestion.evidence_decision_ids, evidence_flag_ids=suggestion.evidence_flag_ids,
        granted_by=granted_by, granted_at=pipeline.now(),
    )
    store().put(COLLECTION, authorization.id, authorization)
    return authorization


def revoke(authorization_id: str, revoked_by: str) -> m.Authorization:
    raw = store().get(COLLECTION, authorization_id)
    if raw is None:
        raise KeyError(authorization_id)
    authorization = m.Authorization.model_validate(raw)
    if authorization.status != "active":
        return _authorization(raw)
    updated = authorization.model_copy(update={
        "status": "revoked", "revoked_by": revoked_by.strip() or "superintendent", "revoked_at": pipeline.now(),
    })
    store().put(COLLECTION, updated.id, updated)
    return _authorization(updated.model_dump())


def _evidence_ok(flag: m.Flag) -> bool:
    event_ids = {item.event_id for item in flag.evidence}
    facts = [fact for fact in store().list("facts") if fact.get("event_id") in event_ids]
    return bool(facts) and all(float(fact.get("confidence") or 0) >= MIN_EVIDENCE_CONFIDENCE for fact in facts)


def _known_task(flag: m.Flag) -> m.Task | None:
    plan = _plan()
    task_id = flag.affected.get("task")
    if task_id:
        return next((task for task in plan.tasks if task.id == task_id), None)
    unit, crew = flag.affected.get("unit"), flag.affected.get("crew")
    if not unit:
        return None
    candidates = [task for task in plan.tasks if task.unit == unit and (not crew or task.crew == crew)]
    return candidates[0] if candidates else None


def _reason(authorization: m.Authorization) -> str:
    granted = authorization.granted_at
    return (f"Held automatically under authorization {authorization.id}, granted by {authorization.granted_by} on "
            f"{granted:%Y-%m-%d %H:%M}, which rests on decisions "
            f"{', '.join(authorization.evidence_decision_ids)}.")


def _notice(decision: m.Decision, authorization: m.Authorization, flag: m.Flag,
            task: m.Task) -> m.OutboundMessage:
    unit = flag.affected.get("unit") or task.unit or "the site"
    text = (f"Held {task.name} in {unit} under your authorization {authorization.id}, because {flag.summary} "
            f"Undo it with Release work on the flag.")
    return m.OutboundMessage(
        id=f"o-{decision.id}-superintendent", channel="telegram", to=authorization.granted_by, text=text,
        buttons=[], reason="Automatic hold under authorization", created_at=decision.decided_at,
    )


def _hold_if_authorized(flag: m.Flag) -> None:
    if flag.status != "open":
        return
    if any(decision.get("flag_id") == flag.id for decision in store().list("decisions")):
        return
    if not _evidence_ok(flag):
        return
    task = _known_task(flag)
    if task is None:
        return
    scope = _scope(flag)
    authorization = next((auth for auth in _authorizations() if auth.status == "active" and auth.scope == scope),
                         None)
    if authorization is None or flag.raised_at <= authorization.granted_at:
        return
    if _holds_today(flag.raised_at.date()) >= DAILY_LIMIT:
        return
    decision = pipeline.decide(m.DecisionRequest(
        flag_id=flag.id, action="hold_work", decided_by=AURORA, reason=_reason(authorization),
        authorization_id=authorization.id,
    ))
    delivery.deliver(_notice(decision, authorization, flag, task))


def on_flags(flags: list[m.Flag]) -> None:
    """Hold the flags an active authorization covers. Every refusal is silent; one bad flag never fails an ingest."""
    for flag in flags:
        try:
            _hold_if_authorized(flag)
        except Exception as error:
            log.error("autonomy: automatic hold skipped for %s: %s", flag.id, type(error).__name__)
