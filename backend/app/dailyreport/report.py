"""The daily report: one site day in plain text, built from the record, and the one send at the end of the day.

Every line carries the source it came from, so a reader can open the event or the flag behind it. No model is
called: the report says what the store already holds.
"""
import os
from collections import OrderedDict
from datetime import date, datetime, timedelta

from app.core import models as m
from app.core import site
from app.core.store import store
from app.live import directory
from app.live.delivery import deliver as _deliver
from app.dailyreport.machines import machine_section
from app.core.registry import area

DEFAULT_REPORT_HOUR = 17
SUPERINTENDENT = "Superintendent"

SECTIONS = OrderedDict([
    ("change", "Changes"),
    ("flag", "Flags raised"),
    ("acknowledgement", "Crew confirmations"),
    ("notice", "Messages Aurora sent"),
    ("decision", "Decisions"),
    ("answer", "Crew questions answered"),
    ("info", "What the crews reported"),
])


def report_hour() -> int:
    try:
        hour = int(os.environ.get("DAILY_REPORT_HOUR") or DEFAULT_REPORT_HOUR)
    except ValueError:
        return DEFAULT_REPORT_HOUR
    return hour if 0 <= hour <= 23 else DEFAULT_REPORT_HOUR


def _moment(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _superintendent() -> str:
    return next((person.name for person in directory.people() if (person.role or "").lower() == "superintendent"),
                SUPERINTENDENT)


def _source(entry: dict) -> str:
    events = [str(event_id) for event_id in entry.get("source_event_ids") or []]
    if events:
        return " [" + ", ".join(events) + "]"
    refs = entry.get("refs") or {}
    return " [" + ", ".join(f"{key} {value}" for key, value in refs.items()) + "]" if refs else ""


def _line(entry: dict) -> str:
    detail = (entry.get("detail") or "").strip()
    if detail and detail != entry["title"]:
        return f"- {entry['title']}: {detail}{_source(entry)}"
    return f"- {entry['title']}{_source(entry)}"


def _tomorrow(day: date) -> str:
    return site.local(datetime.combine(day + timedelta(days=1), datetime.min.time())).strftime("%A %d %b")


def _needs_you(day: date) -> list[str]:
    """An open hold and an unconfirmed change whose work starts the next site day go first, before the day itself."""
    tomorrow = day + timedelta(days=1)
    lines = []
    for flag in store().list("flags"):
        if flag.get("status") not in {"open", "held"} or not flag.get("work_starts_at"):
            continue
        start = _moment(flag["work_starts_at"])
        if start is None or site.local(start).date() != tomorrow:
            continue
        sources = [evidence["event_id"] for evidence in flag.get("evidence") or []]
        suffix = " [" + ", ".join(sources) + "]" if sources else ""
        lines.append(f"- {flag['title']} ({flag['status']}). Work starts {_tomorrow(day)}.{suffix}")
    for item in store().list("waiting"):
        if item.get("status") != "open" or not item.get("due") or not str(item.get("what", "")).startswith("Confirm "):
            continue
        due = _moment(item["due"])
        if due is None or site.local(due).date() != tomorrow:
            continue
        sources = [str(event_id) for event_id in item.get("source_event_ids") or []]
        suffix = " [" + ", ".join(sources) + "]" if sources else ""
        lines.append(f"- {item['on']} has not confirmed yet: {item['what']}. Work starts {_tomorrow(day)}.{suffix}")
    return lines


def build(day: date) -> str | None:
    """The report of one site day, or None when nothing happened and nothing waits for tomorrow."""
    entries: dict[str, list] = OrderedDict((kind, []) for kind in SECTIONS)
    for entry in store().list("record"):
        at = _moment(entry.get("at"))
        if at is None or site.local(at).date() != day:
            continue
        # A start check is a machine or a person asking, not something that happened on site, and its title
        # carries a name the caller chose.
        if (entry.get("refs") or {}).get("check"):
            continue
        entries.setdefault(entry.get("kind"), []).append(entry)
    machines = machine_section(day.isoformat(), store().list("record"), store().list("checks"),
                               [machine.model_dump() for machine in area("machine").machines()], store().list("flags"))
    needs_you = _needs_you(day)
    if not needs_you and not any(entries.values()) and machines is None:
        return None
    project = store().get("project", "current") or {}
    name = project.get("name") or "The site"
    heading = site.local(datetime.combine(day, datetime.min.time())).strftime("%A %d %b %Y")
    lines = [f"{name} daily report for {heading} (site time).", ""]
    if needs_you:
        lines.append("Needs you before tomorrow")
        lines.extend(needs_you)
        lines.append("")
    for kind, title in SECTIONS.items():
        group = entries.get(kind) or []
        if not group:
            continue
        lines.append(title)
        lines.extend(_line(entry) for entry in group)
        lines.append("")
    if machines:
        lines.append(machines["title"])
        lines.extend(f"- {line['text']} [{line['source']['href']}]" for line in machines["lines"])
        lines.append("")
    lines.append("Generated from the Aurora record. Synthetic demo data.")
    return "\n".join(lines)


def _record(day: date, to: str, sent: m.OutboundMessage) -> m.RecordEntry:
    if sent.status == "failed":
        title = f"Daily report for {day.isoformat()} not delivered to {to}"
    else:
        title = f"Daily report for {day.isoformat()} sent to {to}"
    return m.RecordEntry(
        id=f"r-daily-{day.isoformat()}", at=sent.created_at, kind="notice", title=title,
        detail=f"Report for {day.isoformat()}, page /daily/{day.isoformat()}", actor="Aurora",
        refs={"report": day.isoformat(), "message": sent.id})


def send(event: m.InboundEvent) -> m.OutboundMessage | None:
    """Send the day's report at the first event after the report hour, once per site day."""
    local = site.local(event.received_at)
    if local.hour < report_hour():
        return None
    day, who = local.date(), _superintendent()
    message_id = f"o-daily-{day.isoformat()}"
    stored = store().get("outbox", message_id)
    if stored is not None and stored["status"] not in {"failed", "queued"}:
        return None
    if not directory.reach(who, "email"):
        # Without an address in the directory there is nobody to send it to; the report page still shows it.
        return None
    text = build(day)
    if text is None:
        return None
    message = m.OutboundMessage(
        id=message_id, channel="email", to=who, reason="Daily report at the end of the site day",
        text=f"{text}\n\nFull page: /daily/{day.isoformat()}", created_at=event.received_at)
    sent = _deliver(message)
    store().put("record", f"r-daily-{day.isoformat()}", _record(day, who, sent))
    return sent
