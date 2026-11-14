"""Mock: the suggestion and the authorization from mocks/scenario.json, and a granted one in the store."""
from datetime import datetime, timezone

from app.core import models as m
from app.core import scenario
from app.core.store import store

COLLECTION = "authorizations"
DAILY_LIMIT = 5


def _time(value: object) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _generated_at() -> datetime:
    times = []
    for entry in store().list("record"):
        try:
            times.append(datetime.fromisoformat(str(entry.get("at")).replace("Z", "+00:00")))
        except (TypeError, ValueError):
            continue
    return max(times) if times else datetime.now(timezone.utc)


def _canned() -> dict:
    return scenario.load().get("autonomy") or {}


def _suggestion(raw: dict) -> m.AutonomySuggestion:
    return m.AutonomySuggestion.model_validate(raw)


def _authorization(raw: dict) -> m.Authorization:
    return m.Authorization.model_validate(raw)


def _applications(authorization_id: str) -> list[m.AuthorizationApplication]:
    found = []
    for decision in store().list("decisions"):
        if decision.get("authorization_id") != authorization_id:
            continue
        found.append(m.AuthorizationApplication(
            decision_id=decision["id"], flag_id=decision["flag_id"],
            record_entry_id=f"r-dec-{decision['id']}", at=_time(decision.get("decided_at")),
        ))
    return found


def _stored() -> list[m.Authorization]:
    return [_authorization(raw) for raw in store().list(COLLECTION)]


def _holds_today(now: datetime) -> int:
    return sum(1 for decision in store().list("decisions")
               if decision.get("authorization_id") and _time(decision.get("decided_at")).date() == now.date())


def _covers(authorization: m.Authorization, suggestion: m.AutonomySuggestion) -> bool:
    return authorization.action == suggestion.action and authorization.scope == suggestion.scope


def suggest() -> m.Autonomy:
    now = _generated_at()
    by_id = {raw["id"]: _authorization(raw) for raw in _canned().get("authorizations", [])}
    for authorization in _stored():
        by_id[authorization.id] = authorization
    authorizations = list(by_id.values())
    for authorization in authorizations:
        authorization.applications = _applications(authorization.id)
    active = [authorization for authorization in authorizations if authorization.status == "active"]
    suggestions = [suggestion for suggestion in (_suggestion(raw) for raw in _canned().get("suggestions", []))
                   if not any(_covers(authorization, suggestion) for authorization in active)]
    return m.Autonomy(
        generated_at=now,
        suggestions=suggestions,
        authorizations=authorizations,
        automatic_holds_today=_holds_today(now),
        daily_limit=DAILY_LIMIT,
    )


def grant(request: m.AutonomyGrantRequest) -> m.Authorization:
    granted_by = request.granted_by.strip()
    if not granted_by:
        raise ValueError("A grant needs the name of the person granting it.")
    suggestion = next((_suggestion(raw) for raw in _canned().get("suggestions", [])
                       if raw.get("id") == request.suggestion_id), None)
    if suggestion is None:
        raise KeyError(request.suggestion_id)
    existing = store().get(COLLECTION, suggestion.id)
    if existing is not None:
        return _authorization(existing)
    authorization = m.Authorization(
        id=suggestion.id.replace("sug-", "auth-", 1),
        action=suggestion.action,
        flag_type=suggestion.flag_type,
        scope=suggestion.scope,
        statement=suggestion.statement,
        rule_id=f"rule-{suggestion.evidence_decision_ids[-1]}",
        evidence_decision_ids=suggestion.evidence_decision_ids,
        evidence_flag_ids=suggestion.evidence_flag_ids,
        granted_by=granted_by,
        granted_at=_generated_at(),
    )
    store().put(COLLECTION, authorization.id, authorization)
    return authorization


def _find(authorization_id: str) -> m.Authorization | None:
    raw = store().get(COLLECTION, authorization_id)
    if raw is not None:
        return _authorization(raw)
    return next((_authorization(row) for row in _canned().get("authorizations", [])
                 if row.get("id") == authorization_id), None)


def revoke(authorization_id: str, revoked_by: str) -> m.Authorization:
    authorization = _find(authorization_id)
    if authorization is None:
        raise KeyError(authorization_id)
    if authorization.status != "active":
        return authorization
    authorization.status = "revoked"
    authorization.revoked_by = revoked_by.strip() or "superintendent"
    authorization.revoked_at = _generated_at()
    store().put(COLLECTION, authorization.id, authorization)
    return authorization


def on_flags(flags: list[m.Flag]) -> None:
    """The mock never holds anything by itself; the mechanism is a separate feature."""
    return None
