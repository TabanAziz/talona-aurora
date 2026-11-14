"""Compare arrived supplier updates with the stored resource plan."""
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone

from app.core import config, models as m
from app.core.store import store


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _date(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return timestamp.astimezone(timezone.utc).date() if timestamp.tzinfo else None
    except ValueError:
        return None


def _late(value: str, planned: datetime) -> bool:
    if len(value) == 10:
        return date.fromisoformat(value) > planned.date()
    return datetime.fromisoformat(value.replace("Z", "+00:00")) > planned


def _matches(fact: m.Fact, resource: m.ResourceLine) -> bool:
    if _text(fact.data.get("item")).casefold() != resource.item.casefold():
        return False
    if fact.type != f"{resource.kind}_actual":
        return False
    raw_date = fact.data.get("planned_date") or fact.data.get("date" if resource.kind == "delivery" else "planned_date")
    if raw_date is None:
        return resource.kind == "equipment" or _date(fact.data.get("actual_date")) is not None
    return _date(raw_date) == resource.date.date()


def _identity(resource: m.ResourceLine, flags: list[m.Flag]) -> str:
    planned_date = resource.date.isoformat()
    for flag in flags:
        if flag.type == "plan_deviation" and flag.affected.get("resource") == resource.id \
                and flag.affected.get("planned_date") == planned_date:
            return flag.id
    slug = re.sub(r"[^a-z0-9]+", "-", resource.id.removeprefix("R-").lower()).strip("-")
    base = f"f-{slug}"
    if any(flag.id == base for flag in flags):
        return base + "-" + hashlib.sha256(f"{resource.id}|{planned_date}".encode()).hexdigest()[:12]
    return base


def _candidates(fact: m.Fact, resources: list[m.ResourceLine]) -> list[m.ResourceLine]:
    matches = [resource for resource in resources if _matches(fact, resource)]
    if matches or fact.type != "delivery_actual" or fact.data.get("planned_date") or _date(fact.data.get("actual_date")) is None:
        return matches
    named = [resource for resource in resources if resource.kind == "delivery"
             and resource.item.casefold() == _text(fact.data.get("item")).casefold()]
    return named if len(named) == 1 else []


def _task(fact: m.Fact, resource: m.ResourceLine, plan: m.Plan) -> m.Task | None:
    task_id = _text(fact.data.get("task"))
    path = config.project_metadata_file()
    if not task_id and path.is_file():
        project = json.loads(path.read_text(encoding="utf-8"))
        links = [item for item in project.get("resources", []) if item.get("id") == resource.id]
        if len(links) == 1:
            task_id = _text(links[0].get("task"))
    if not task_id and any(task.id == resource.id for task in plan.tasks):
        task_id = resource.id
    return next((task for task in plan.tasks if task.id == task_id), None)


def _deviation(resource: m.ResourceLine, planned: float, actual: float, arrival: str | None) -> tuple[int, float] | None:
    """Size and direction of a deviation: truck counts for deliveries, days for equipment."""
    if resource.kind == "delivery":
        delta = actual - planned
        if delta == 0:
            return None
        return (1 if delta > 0 else -1, abs(delta))
    arrived = _date(arrival) if arrival else None
    if arrived is None:
        return None
    days = (arrived - resource.date.date()).days
    if days <= 0:
        return None
    return (1, float(days))


def _rule_numbers(rule: dict) -> dict:
    numbers = rule.get("numbers")
    if isinstance(numbers, dict):
        return numbers
    # Rules kept before the decision snapshotted its numbers still name the incident flag.
    raw = store().get("flags", _text(rule.get("flag_id")))
    fallback = (raw or {}).get("numbers")
    return fallback if isinstance(fallback, dict) else {}


def _accepted(rule: dict) -> tuple[str, str, int, float] | None:
    """Item, kind, direction and amount a standing rule covers, or None when it does not apply to deviations."""
    scope = rule.get("scope") if isinstance(rule.get("scope"), dict) else {}
    decided_on = rule.get("decided_on") if isinstance(rule.get("decided_on"), dict) else {}
    if rule.get("status", "active") != "active" or scope.get("flag_type") != "plan_deviation":
        return None
    if rule.get("action") not in ("dismiss", "reschedule"):
        return None
    item = _text(scope.get("item")).casefold()
    if not item:
        return None
    if decided_on.get("actual_date"):
        planned_at, arrived = _date(decided_on.get("planned_date")), _date(decided_on.get("actual_date"))
        if planned_at is None or arrived is None or (arrived - planned_at).days <= 0:
            return None
        return item, "equipment", 1, float((arrived - planned_at).days)
    numbers = _rule_numbers(rule)
    planned, actual = _number(numbers.get("planned")), _number(numbers.get("actual"))
    if planned is None or actual is None or actual == planned:
        return None
    delta = actual - planned
    return item, "delivery", (1 if delta > 0 else -1), abs(delta)


def _tolerance(resource: m.ResourceLine, deviation: tuple[int, float]) -> dict | None:
    """The newest active rule that already accepted a deviation at least this large in the same direction."""
    direction, amount = deviation
    item = resource.item.casefold()
    best: dict | None = None
    for rule in store().list("rules"):
        accepted = _accepted(rule)
        if accepted is None:
            continue
        rule_item, kind, rule_direction, rule_amount = accepted
        if rule_item != item or kind != resource.kind:
            continue
        if rule_direction != direction or rule_amount < amount:
            continue
        if best is None or str(rule.get("decided_at", "")) > str(best.get("decided_at", "")):
            best = rule
    return best


def _cited(summary: str, rule: dict) -> str:
    decided_at = _date(str(rule.get("decided_at", "")))
    when = decided_at.isoformat() if decided_at else "an earlier decision"
    who = _text(rule.get("decided_by")) or "the superintendent"
    return f"{summary} Inside what {who} accepted on {when} for similar cases."


def evaluate(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.Flag]:
    """Return sourced deviations without changing the schedule or resource plan."""
    s = store()
    raw_plan = s.get("plan", "current")
    if raw_plan is None:
        return []
    plan = m.Plan.model_validate(raw_plan)
    events = {raw["id"]: m.InboundEvent.model_validate(raw) for raw in s.list("events")}
    events[event.id] = event
    known = {raw["id"]: m.Fact.model_validate(raw) for raw in s.list("facts")}
    known.update({f.id: f for f in facts if f.event_id == event.id})
    arrived = [f for f in known.values() if f.event_id in events
               and events[f.event_id].received_at <= event.received_at]
    existing = [m.Flag.model_validate(raw) for raw in s.list("flags")]
    emitted = {}
    for fact in facts:
        if fact.event_id != event.id or fact.type not in ("delivery_actual", "equipment_actual"):
            continue
        matches = _candidates(fact, plan.resources)
        if len(matches) != 1:
            continue
        resource = matches[0]
        reports = [f for f in arrived if resource in _candidates(f, plan.resources)]
        latest = max(reports, key=lambda f: (events[f.event_id].sent_at, events[f.event_id].received_at, f.id))
        if latest.id != fact.id:
            continue
        planned = _number(resource.planned)
        if planned is None:
            continue
        flag_id = _identity(resource, existing + list(emitted.values()))
        previous = next((f for f in existing if f.id == flag_id), None)
        affected = {"resource": resource.id, "item": resource.item, "planned_date": resource.date.isoformat()}
        task = _task(fact, resource, plan)
        if task:
            affected.update(task=task.id, crew=task.crew)
        arrival = None
        reported_count = None
        if resource.kind == "delivery":
            actual = _number(fact.data.get("actual"))
            arrival = fact.data.get("actual_date")
            late = _date(arrival) is not None and _late(arrival, resource.date)
            if actual is None and _date(arrival) is None:
                continue
            reported_count = actual
            actual = (_number((previous.numbers or {}).get("actual")) if previous else None) if actual is None else actual
            actual = planned if actual is None else actual
            deviates = actual != planned or late
            if _date(arrival) is not None:
                affected["actual_date"] = arrival
            if late:
                title = f"{resource.item} is delayed"
                summary = f"The supplier reports arrival on {arrival}; the delivery was booked for {resource.date.isoformat()}."
                if reported_count is not None:
                    summary += f" Quantity: {actual:g} {resource.unit}, {planned:g} planned."
            else:
                title = f"{resource.item}: {actual:g} expected, {planned:g} planned"
                summary = f"The supplier reports {actual:g} {resource.unit}; the plan requires {planned:g}."
        else:
            arrival = fact.data.get("actual_date")
            if _date(arrival) is None:
                continue
            deviates = _late(arrival, resource.date) and planned > 0
            actual = 0.0 if deviates else planned
            affected["actual_date"] = arrival
            title = f"{resource.item} {'arrives after' if deviates else 'is available for'} its planned use"
            summary = f"Arrival is {arrival}; the resource is planned for {resource.date.isoformat()}."
        if not deviates and previous is None:
            continue
        status = previous.status if previous else "open"
        if not deviates and status == "open":
            status = "resolved"
        elif deviates and status == "resolved" and not any(
                decision.get("flag_id") == flag_id for decision in s.list("decisions")):
            status = "open"
        severity = "high" if resource.kind == "equipment" or arrival and _date(arrival) and _late(arrival, resource.date) else "medium"
        if deviates and status == "open":
            deviation = _deviation(resource, planned, actual, arrival)
            if resource.kind == "delivery" and arrival and _date(arrival) and _late(arrival, resource.date):
                deviation = None
            rule = _tolerance(resource, deviation) if deviation else None
            if rule is not None:
                # The record keeps the incident, but a line the superintendent already drew stays quiet.
                status, severity = "dismissed", "low"
                summary = _cited(summary, rule)
        emitted[flag_id] = m.Flag(
            id=flag_id, type="plan_deviation", severity=severity,
            title=title, summary=summary, status=status,
            raised_at=previous.raised_at if previous else event.received_at, work_starts_at=resource.date,
            affected=affected, numbers={"planned": planned, **({"actual": actual} if resource.kind != "delivery" or reported_count is not None else {})},
            proposal_id=previous.proposal_id if previous else None,
            evidence=[m.Evidence(event_id=event.id, channel=event.channel, sender=event.sender,
                                 at=event.sent_at, quote=fact.quote or event.transcript or event.text)],
        )
    return list(emitted.values())
