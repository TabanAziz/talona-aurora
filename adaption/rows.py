"""The row format shared by the Adaption source, the generated rows and history.json. Standard library only.

A row is a prompt that names channel, sender, day and time, and a completion that holds the message text. Days are
counted from the demo anchor (the scenario's Thursday), so the same rows work for any demo day.
"""
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = ROOT / "data" / "messages"
# The scenario day the backend shifts to DEMO_ANCHOR (app.demodata.SCENARIO_DAY); check.py asserts both agree.
ANCHOR_DAY = date(2026, 11, 12)
CHANNELS = ("email", "telegram", "schedule")
THREAD = "Maple Court site"
DELIVERY_DELAY_S = {"telegram": 3, "email": 25, "schedule": 0}

PROMPT_PATTERN = re.compile(
    r"Channel:\s*(?P<channel>[a-z]+)\.\s*"
    r"From:\s*(?P<sender>[^,.]+?)(?:,\s*(?P<role>[^.]+?))?\.\s*"
    r"Day:\s*(?P<day>[+-]?\d+)\.\s*"
    r"Time:\s*(?P<time>\d{1,2}:\d{2})\.?"
    r"(?:\s*Subject:\s*(?P<subject>.+?))?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def prompt(channel: str, sender: str, role: str | None, day: int, clock: str, subject: str | None = None) -> str:
    who = f"{sender}, {role}" if role else sender
    text = f"Maple Court site message. Channel: {channel}. From: {who}. Day: {day}. Time: {clock}."
    return f"{text} Subject: {subject}" if subject else text


def parse_prompt(text: str) -> dict | None:
    """The fields of a prompt, or None when it does not follow the format."""
    match = PROMPT_PATTERN.search(text or "")
    if not match:
        return None
    hours, minutes = (int(part) for part in match["time"].split(":"))
    if hours > 23 or minutes > 59:
        return None
    return {
        "channel": match["channel"].lower(),
        "sender": match["sender"].strip(),
        "role": (match["role"] or "").strip() or None,
        "day": int(match["day"]),
        "time": f"{hours:02d}:{minutes:02d}",
        "subject": (match["subject"] or "").strip().rstrip(".") or None,
    }


def offset(moment: str) -> tuple[int, str]:
    """Day offset from the anchor and UTC time of an ISO timestamp."""
    at = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    return (at.date() - ANCHOR_DAY).days, f"{at:%H:%M}"


def anchor_day(value: str | None) -> date:
    """The day a history row's day 0 falls on: `today` (UTC), YYYY-MM-DD, or unset for the scenario's own day."""
    value = (value or "").strip().lower()
    if not value:
        return ANCHOR_DAY
    if value == "today":
        return datetime.now(timezone.utc).date()
    return date.fromisoformat(value)


def to_event(row: dict, day0: date = ANCHOR_DAY) -> dict:
    """A history row as an InboundEvent document, with the same delivery delays as data/messages."""
    hours, minutes = (int(part) for part in row["time"].split(":"))
    sent = datetime.combine(day0 + timedelta(days=row["day"]), time(hours, minutes), tzinfo=timezone.utc)
    received = sent + timedelta(seconds=DELIVERY_DELAY_S[row["channel"]])
    return {
        "id": row["id"],
        "channel": row["channel"],
        "sent_at": sent.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "received_at": received.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sender": row["sender"],
        "sender_role": row["sender_role"],
        "thread": THREAD if row["channel"] == "telegram" else None,
        "subject": row["subject"],
        "text": row["text"],
        "transcript": None,
        "attachments": [],
    }


def source_rows() -> list[dict]:
    """One row per delivery in data/messages/events.json; voice notes carry what the speaker says."""
    events = json.loads((MESSAGES / "events.json").read_text(encoding="utf-8"))
    spoken = json.loads((MESSAGES / "voice_texts.json").read_text(encoding="utf-8"))
    rows = []
    for event in events:
        text = event["text"] or spoken.get(event["id"], {}).get("text", "")
        day, clock = offset(event["sent_at"])
        rows.append({
            "prompt": prompt(event["channel"], event["sender"], event["sender_role"], day, clock, event["subject"]),
            "completion": text,
        })
    return rows


def project() -> dict:
    """Units, sheets, crews and who may send what, from data/project/project.json."""
    raw = json.loads((ROOT / "data" / "project" / "project.json").read_text(encoding="utf-8"))
    senders = {"Schedule update": {"role": None, "crew": None, "channels": ("schedule",)}}
    for crew in raw["crews"]:
        role = re.sub(r"\s+crew$", "", crew["name"]) + " foreman"
        senders[crew["foreman"]] = {"role": role, "crew": crew["name"], "channels": ("telegram", "email")}
    for contact in raw["contacts"]:
        senders[contact["name"]] = {"role": contact["role"], "crew": None, "channels": ("telegram", "email")}
    return {
        "units": list(raw["project"]["units"]),
        "sheets": list(raw["project"]["sheets"]),
        "crews": list(raw["project"]["crews"]),
        "senders": senders,
    }


UNIT_TOKEN = re.compile(r"\b(\d[A-Z])\b")
SHEET_TOKEN = re.compile(r"\b([A-Z]{1,2}-\d{3})\b")
TASK_TOKEN = re.compile(r"\b(T-\d{3})\b")
ABSOLUTE_DATE = re.compile(
    # "May" is left out on purpose: as a verb it is far more common in site chat than the month.
    r"\b(20\d\d-\d\d-\d\d|\d{1,2}[./]\d{1,2}[./]\d{2,4}|january|february|march|april|june|july|august|"
    r"september|october|november|december|jan|feb|apr|jun|jul|aug|sept|oct|nov|dec)\b",
    re.IGNORECASE,
)


def refs(row: dict, known: dict) -> dict:
    """What a row names: units, sheets, tasks and crews, plus the names it uses that the project does not know."""
    text = " ".join(filter(None, [row.get("subject"), row.get("text")]))
    units = sorted(set(UNIT_TOKEN.findall(text)))
    sheets = sorted(set(SHEET_TOKEN.findall(text)))
    tasks = sorted(set(TASK_TOKEN.findall(text)))
    crews = sorted({c for c in known["crews"] if c.lower() in text.lower()})
    sender_crew = known["senders"].get(row.get("sender"), {}).get("crew")
    if sender_crew and sender_crew not in crews:
        crews = sorted([*crews, sender_crew])
    return {
        "units": [u for u in units if u in known["units"]],
        "sheets": [s for s in sheets if s in known["sheets"]],
        "tasks": tasks,
        "crews": crews,
        "unknown": [u for u in units if u not in known["units"]] + [s for s in sheets if s not in known["sheets"]],
    }


def problems(row: dict, known: dict) -> list[str]:
    """Why a history row cannot be used; an empty list means it can."""
    found = []
    sender = known["senders"].get(row.get("sender"))
    if row.get("channel") not in CHANNELS:
        found.append(f"channel {row.get('channel')!r} is not one of {', '.join(CHANNELS)}")
    if sender is None:
        found.append(f"sender {row.get('sender')!r} is not in data/project")
    else:
        if row.get("sender_role") != sender["role"]:
            found.append(f"role {row.get('sender_role')!r} does not match {sender['role']!r}")
        if row.get("channel") not in sender["channels"]:
            found.append(f"{row.get('sender')} does not send on {row.get('channel')}")
    if not isinstance(row.get("day"), int) or not re.fullmatch(r"\d\d:\d\d", str(row.get("time", ""))):
        found.append("day and time must be an offset and HH:MM")
    if not (row.get("text") or "").strip():
        found.append("text is empty")
    if row.get("channel") == "email" and not row.get("subject"):
        found.append("an email needs a subject")
    if ABSOLUTE_DATE.search(" ".join(filter(None, [row.get("subject"), row.get("text")]))):
        found.append("text names an absolute date")
    named = refs(row, known)
    if named["unknown"]:
        found.append(f"names {', '.join(named['unknown'])}, which the project does not have")
    if named["tasks"]:
        found.append("names a schedule task id instead of the work")
    if not (named["units"] or named["sheets"] or named["crews"]):
        found.append("maps to no unit, crew, sheet or task")
    return found


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8",
                    newline="\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
