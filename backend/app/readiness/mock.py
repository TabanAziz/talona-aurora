"""Mock: the readiness picture from the plan and the start check, briefings sent once per day and crew."""
import re
from datetime import date, datetime, timedelta, timezone

from app.core import models as m
from app.core import scenario
from app.core.registry import area
from app.core.store import store
from app.live import delivery

DONE = ("sent", "simulated")


def evaluate(day: date | None = None) -> m.Readiness:
    return _picture(day, send=False)


def run(day: date | None = None) -> m.Readiness:
    return _picture(day, send=True)


def _plan() -> m.Plan:
    stored = store().get("plan", "current")
    return m.Plan.model_validate(stored) if stored else area("schedule").baseline()


def _time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _generated_at() -> datetime:
    times = [
        at for at in (_time(event.get("received_at")) for event in store().list("events")) if at is not None
    ]
    return max(times) if times else datetime.now(timezone.utc)


def _day(day: date | None) -> date:
    """The day after the latest event, unless the caller names the day."""
    return day if day is not None else (_generated_at() + timedelta(days=1)).date()


def _status(check: m.StartCheck) -> m.ReadinessStatus:
    if check.allowed == "unknown":
        return "unknown"
    if any(reason.blocking for reason in check.reasons):
        return "blocked"
    return "at_risk" if check.reasons else "ready"


def _when(item: m.ReadinessItem) -> str:
    place = f" in {item.unit}" if item.unit else ""
    return f"{item.name} at {item.start.strftime('%H:%M')}{place}"


def _brief(day: date, items: list[m.ReadinessItem], generated: datetime) -> list[m.OutboundMessage]:
    """One message per crew. The id comes from the day and the crew, so a second run sends nothing new."""
    words = scenario.load()["readiness"]
    sent: list[m.OutboundMessage] = []
    for crew in dict.fromkeys(item.crew for item in items):
        message_id = f"o-briefing-{day.isoformat()}-{re.sub(r'[^a-z0-9]+', '-', crew.lower()).strip('-')}"
        stored = store().get("outbox", message_id)
        if stored is not None and stored.get("status") in DONE:
            continue
        own = [item for item in items if item.crew == crew]
        lines = [f"{day.strftime('%A %d %B')} for {crew}: " + ", ".join(_when(item) for item in own)]
        open_points = sorted(
            ((item, reason) for item in own for reason in item.reasons),
            key=lambda pair: (not pair[1].blocking, pair[1].kind),
        )
        lines += [f"Before you start {item.name}: {reason.text}" for item, reason in open_points]
        if not open_points:
            lines.append(words["all_clear"])
        message = m.OutboundMessage(
            id=message_id, channel="telegram", to=crew, text="\n".join(lines), buttons=[words["got_it"]],
            reason=f"Tomorrow on site, {day.isoformat()}", created_at=generated,
        )
        # Telegram is where the demo crews are reached; the real module picks each crew's channel from
        # the directory. Delivery is the one way a message leaves the app, and it stores the outcome.
        delivered = delivery.deliver(message)
        if delivered.status in ("sent", "simulated"):
            sent.append(delivered)
    return sent


def _picture(day: date | None, send: bool) -> m.Readiness:
    target = _day(day)
    generated = _generated_at()
    gate = area("gate")
    items: list[m.ReadinessItem] = []
    for task in sorted(_plan().tasks, key=lambda task: task.start):
        if task.start.date() != target:
            continue
        check = gate.check(m.StartCheckRequest(asked_by="readiness", task_id=task.id))
        items.append(m.ReadinessItem(
            task_id=task.id, name=task.name, unit=task.unit, crew=task.crew, start=task.start,
            status=_status(check), reasons=check.reasons,
        ))
    briefings = _brief(target, items, generated) if send else []
    return m.Readiness(day=target, generated_at=generated, items=items, briefings=briefings)
