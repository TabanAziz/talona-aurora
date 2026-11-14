"""What the record should know by now and does not, asked once, and the loop a reply closes.

No model call: the plan, the facts, the record and the directory decide. The hook in `outbox.react` runs
`react()` for every ingested event, so the clock is the event being played back and a reply is matched in the
same pass. A reply that an inspection passed is stored as an `inspection_passed` fact, so the rules and the crew
answers see it like any other sign-off.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core import config, models as m
from app.core.registry import area
from app.core.store import store
from app.live import directory

# The two thresholds of this area, in one place: how long after the expected time a silence counts, and how near
# the work must be for the answer to still matter.
STALE_AFTER = timedelta(minutes=60)
LOOKAHEAD = timedelta(hours=24)
BUTTONS = ["Passed", "Not passed", "Still open"]
SCHEDULING = {"inspection_scheduled", "inspection_moved"}
SIGN_OFF = ("passed", "signed off", "sign-off received")
INSPECTOR_ROLES = ("inspector",)
DELIVERY_ROLES = ("supplier", "dispatch")
EQUIPMENT_ROLES = ("crane", "operator")
SUPERINTENDENT = "Superintendent"
RETRY = ("failed", "queued")
PASSED_WORDS = re.compile(r"^(passed|pass|signed off|sign-off received|yes,? (it )?passed)$", re.I)
NOT_PASSED_WORDS = re.compile(r"^(not passed|not ok|failed|fail|still open|late|no|not yet)$", re.I)
NOT_PASSED_TEXT = re.compile(r"\b(not passed|not ok|failed|still open|not signed off|no sign-off|late)\b", re.I)
PASSED_TEXT = re.compile(r"\b(passed|signed off|sign-off received)\b", re.I)
COVER_UP = re.compile(r"\b(clos\w*|board\w*|insulat\w*|sheath\w*|ceilings?|backfill\w*|cover\w*|tap\w*|hang\w*)\b")


@dataclass(frozen=True)
class Gap:
    """One thing the record expected by `now` and has no result for."""

    kind: str
    name: str
    unit: str
    at: datetime
    due: datetime
    task: m.Task
    vehicle: bool = False
    source_event_ids: tuple[str, ...] = ()


def gaps(now: datetime) -> list[Gap]:
    """Rubber-stamp free: every gap the plan and the record disagree about at `now`."""
    now = _utc(now)
    if now is None:
        return []
    found: list[Gap] = []
    plan = _plan()
    for task in plan.tasks:
        if task.status != "planned" or not task.requires_inspection:
            continue
        start = _utc(task.start)
        if start is None or start <= now or start > now + LOOKAHEAD:
            continue
        unit = task.unit or ""
        inspection = _inspection_name(task.requires_inspection, unit)
        if not inspection or _passed(unit, inspection):
            continue
        scheduled = _scheduled(unit, inspection)
        if scheduled is None or scheduled[0] > now - STALE_AFTER:
            continue
        found.append(Gap("inspection", inspection, unit, scheduled[0], start, task,
                         source_event_ids=(scheduled[1],)))
    served = _served()
    for line in plan.resources:
        if line.kind not in ("delivery", "equipment"):
            continue
        planned = _utc(line.date)
        task = served.get(line.id)
        if planned is None or planned > now - STALE_AFTER or _reported(line) or task is None:
            continue
        start = _utc(task.start)
        if task.status != "planned" or start is None or start <= now:
            continue
        found.append(Gap("resource", line.item, "", planned, start, task, vehicle=line.kind == "equipment"))
    return _unique(found)


def react(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.OutboundMessage]:
    """One pass per event: a reply closes its question, and every gap that is due gets exactly one ask."""
    now = _utc(event.received_at)
    messages = _replies(event, now)
    if now is not None:
        messages.extend(_ask(gaps(now), now))
    # Timer asks are ordinary; late answers carry their own original question in in_reply_to.
    return [area("guest").bind_delivery(message, []) for message in messages]


def _unique(found: list[Gap]) -> list[Gap]:
    """One ask per case: the same inspection for a unit asked for two tasks stays one question."""
    unique: dict[tuple[str, str, str], Gap] = {}
    for gap in found:
        key = (gap.kind, gap.name.casefold(), gap.unit.casefold())
        if key not in unique or gap.due < unique[key].due:
            unique[key] = gap
    return sorted(unique.values(), key=lambda gap: gap.due)


def _key(gap: Gap) -> str:
    identity = "|".join([gap.kind, gap.name.casefold(), gap.unit.casefold(), gap.at.date().isoformat()])
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


def _ask(found: list[Gap], now: datetime) -> list[m.OutboundMessage]:
    s = store()
    messages: list[m.OutboundMessage] = []
    for gap in found:
        key = _key(gap)
        message_id = f"o-followup-{key}"
        waiting_id = f"w-followup-{key}"
        stored = s.get("outbox", message_id)
        if stored is not None and stored.get("status") in RETRY:
            messages.append(m.OutboundMessage.model_validate(stored))
            continue
        if stored is not None or s.get("waiting", waiting_id) is not None:
            continue
        who, channel = _who(gap)
        s.put("waiting", waiting_id, m.WaitingItem(
            id=waiting_id, on=who, what=_question(gap), since=now, due=gap.due,
            source_event_ids=list(gap.source_event_ids),
        ))
        messages.append(m.OutboundMessage(
            id=message_id, channel=channel, to=who, text=_text(gap), buttons=list(BUTTONS),
            reason=f"Follow-up: {_reason(gap)}", created_at=now,
        ))
    return messages


def _who(gap: Gap) -> tuple[str, str]:
    """The inspector, the supplier or crane operator, and the superintendent when nobody that specific is known."""
    words = INSPECTOR_ROLES if gap.kind == "inspection" else (EQUIPMENT_ROLES if gap.vehicle else DELIVERY_ROLES)
    people = directory.people()
    for person in people:
        role = _norm(person.role)
        channel = _channel(person.name)
        if any(word in role for word in words) and channel:
            return person.name, channel
    superintendent = next((person.name for person in people if "superintendent" in _norm(person.role)), SUPERINTENDENT)
    return superintendent, _channel(superintendent) or "telegram"


def _channel(name: str) -> str | None:
    for channel in ("telegram", "email", "whatsapp"):
        if directory.reach(name, channel):
            return channel
    return None


def _text(gap: Gap) -> str:
    work = _lower_first(gap.task.name)
    if gap.kind == "inspection":
        return (f"Aurora here, from the record. The {gap.name} inspection for {gap.unit} was expected "
                f"{_stamp(gap.at)} and has no result on record. {work} starts {_stamp(gap.due)}. "
                f"Has the inspection passed?")
    return (f"Aurora here, from the record. {gap.name} was planned for {_stamp(gap.at)} and no arrival is on "
            f"record. {work} starts {_stamp(gap.due)}. Has it arrived?")


def _question(gap: Gap) -> str:
    if gap.kind == "inspection":
        return f"Report the result of the {gap.name} {gap.unit} inspection"
    return f"Report the arrival of {gap.name}"


def _reason(gap: Gap) -> str:
    if gap.kind == "inspection":
        return f"no result for the {gap.name} {gap.unit} inspection, due {_stamp(gap.at)}"
    return f"no actual value for {gap.name}, planned {_stamp(gap.at)}"


def _replies(event: m.InboundEvent, now: datetime) -> list[m.OutboundMessage]:
    items = [
        item for item in store().list("waiting")
        if str(item.get("id", "")).startswith("w-followup-") and item.get("status") == "open"
    ]
    if not items:
        return []
    verdict = _verdict(event)
    if verdict is None:
        return []
    item = _match(event, items)
    if item is None:
        return []
    store().put("waiting", item["id"], {**item, "status": "done"})
    gap = _gap_of(item)
    _record_reply(item, event, verdict)
    messages: list[m.OutboundMessage] = []
    if verdict == "passed" and gap is not None and gap[0] == "inspection":
        _passed_fact(item, event, gap)
        messages.extend(_follow_up_answers(event, gap, now))
    return messages


def _match(event: m.InboundEvent, items: list[dict]) -> dict | None:
    """A button press keeps the question it answers as its subject; a free text reply comes from the person asked
    and names the inspection or unit it is about."""
    if event.subject:
        for item in items:
            message = store().get("outbox", _message_id(item["id"]))
            if message is not None and _norm(message.get("text")) == _norm(event.subject):
                return item
    sender = _person(event)
    own = [item for item in items if _norm(item.get("on")) == _norm(sender or event.sender)]
    # A bare verdict carries nothing that could point at another inspection, so with one open item it can only
    # answer that item; a sentence with more in it has to name what it is about.
    bare = _norm(event.text).rstrip(".! ")
    if len(own) == 1 and (PASSED_WORDS.fullmatch(bare) or NOT_PASSED_WORDS.fullmatch(bare)):
        return own[0]
    text = f"{event.text} {event.subject or ''}"
    named = [item for item in own if any(_has_word(part, text) for part in _names(item))]
    return named[0] if len(named) == 1 else None


def _verdict(event: m.InboundEvent) -> str | None:
    text = (event.text or "").strip()
    if not text:
        text = _norm(event.subject)
    if not text:
        return None
    if NOT_PASSED_WORDS.fullmatch(text) or NOT_PASSED_TEXT.search(text):
        return "not_passed"
    if PASSED_WORDS.fullmatch(text) or PASSED_TEXT.search(text):
        return "passed"
    return None


def _record_reply(item: dict, event: m.InboundEvent, verdict: str) -> None:
    entry_id = f"r-reply-{item['id']}"
    label = "passed" if verdict == "passed" else "did not pass"
    store().put("record", entry_id, m.RecordEntry(
        id=entry_id, at=event.sent_at, kind="acknowledgement",
        title=f"{event.sender} reported: {label}",
        detail=(event.transcript or event.text or event.subject or "").strip() or None,
        actor=event.sender, source_event_ids=[event.id], refs={"followup": item["id"]},
    ))


def _passed_fact(item: dict, event: m.InboundEvent, gap: tuple[str, str, str]) -> None:
    _, name, unit = gap
    fact_id = f"f-followup-{item['id']}"
    if store().get("facts", fact_id) is not None:
        return
    store().put("facts", fact_id, m.Fact(
        id=fact_id, event_id=event.id, type="inspection_passed",
        subject=f"{name} {unit} passed".strip(),
        data={"unit": unit, "inspection": name, "time": event.sent_at.isoformat()},
        confidence=1, quote=(event.transcript or event.text or event.subject or "").strip() or None,
    ))


def _follow_up_answers(event: m.InboundEvent, gap: tuple[str, str, str], now: datetime) -> list[m.OutboundMessage]:
    """One late answer for each earlier question about this case that the record could not answer."""
    _, name, unit = gap
    source = _evidence(event)
    messages: list[m.OutboundMessage] = []
    for answer in store().list("answers"):
        if answer.get("basis") != "unknown" or not _asks_about(answer, unit, name):
            continue
        follow_id = f"a-followup-{answer['id']}"
        if store().get("answers", follow_id) is not None:
            continue
        text = f"Yes. The {name} inspection for {unit} has passed; {source.sender} reported it {_stamp(source.at)}."
        store().put("answers", follow_id, m.Answer(
            id=follow_id, event_id=answer.get("event_id") or event.id, question=answer.get("question") or "",
            text=text, basis="record", sources=[source], escalated=False, created_at=now,
        ))
        original = store().get("events", answer.get("event_id") or "")
        if original is not None:
            messages.append(m.OutboundMessage(
                id=f"o-followup-{answer['id']}", channel=original["channel"], to=original["sender"],
                text=f"{text}\nSource: {source.sender}, {source.at.isoformat()}: {source.quote}",
                reason="Follow-up answer after the missing inspection result arrived",
                in_reply_to=original["id"], created_at=now,
            ))
    return messages


def _gap_of(item: dict) -> tuple[str, str, str] | None:
    """The inspection and unit (or the resource item) a waiting item was asked about, read from its question."""
    what = _norm(item.get("what"))
    plan = _plan()
    for task in plan.tasks:
        if not task.requires_inspection:
            continue
        unit = task.unit or ""
        name = _inspection_name(task.requires_inspection, unit)
        if name and name in what and _has_word(unit, what):
            return "inspection", name, unit
    for line in plan.resources:
        if line.item and _norm(line.item) in what:
            return "resource", line.item, ""
    return None


def _names(item: dict) -> list[str]:
    gap = _gap_of(item)
    return [gap[1], gap[2]] if gap is not None else []


def _message_id(waiting_id: str) -> str:
    return waiting_id.replace("w-followup-", "o-followup-", 1)


def _asks_about(answer: dict, unit: str, name: str) -> bool:
    question = _norm(answer.get("question"))
    if not unit or not _has_word(unit, question):
        return False
    if name and name in question:
        return True
    facts = [fact for fact in store().list("facts") if fact.get("event_id") == answer.get("event_id")]
    topics = " ".join(_norm((fact.get("data") or {}).get(key)) for fact in facts for key in ("topic", "inspection"))
    return bool(name and name in topics) or COVER_UP.search(question) is not None


def _person(event: m.InboundEvent):
    contact = directory.lookup(event.sender) or directory.resolve(event.channel, event.sender)
    return contact.name if contact is not None and contact.known else None


def _evidence(event: m.InboundEvent) -> m.Evidence:
    text = event.transcript or event.text or event.subject or ""
    return m.Evidence(event_id=event.id, channel=event.channel, sender=event.sender, at=event.sent_at, quote=text)


def _passed(unit: str, inspection: str) -> bool:
    for fact in store().list("facts"):
        if fact.get("type") == "inspection_passed" and _matches(fact.get("data") or {}, unit, inspection):
            return True
    for entry in store().list("record"):
        title = _norm(entry.get("title"))
        refs = entry.get("refs") or {}
        if _unit(refs.get("unit")) != _unit(unit) or inspection not in title:
            continue
        if any(word in title for word in SIGN_OFF) and not NOT_PASSED_TEXT.search(title):
            return True
    return False


def _scheduled(unit: str, inspection: str) -> tuple[datetime, str] | None:
    latest = None
    for fact in store().list("facts"):
        if fact.get("type") not in SCHEDULING or not _matches(fact.get("data") or {}, unit, inspection):
            continue
        data = fact.get("data") or {}
        at = _time(data.get("new_time") or data.get("time"))
        if at is not None and (latest is None or at > latest[0]):
            latest = (at, fact["event_id"])
    return latest


def _reported(line: m.ResourceLine) -> bool:
    planned = _utc(line.date)
    for fact in store().list("facts"):
        if fact.get("type") != f"{line.kind}_actual":
            continue
        data = fact.get("data") or {}
        if _norm(data.get("item")) != _norm(line.item):
            continue
        named = _time(data.get("date" if line.kind == "delivery" else "planned_date"))
        if named is None or planned is None or named.date() == planned.date():
            return True
    return False


def _served() -> dict[str, m.Task]:
    """The task a resource line serves, named by the `task` field of data/project."""
    path = config.project_metadata_file()
    if not path.is_file():
        return {}
    try:
        project = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tasks = {task.id: task for task in _plan().tasks}
    served: dict[str, m.Task] = {}
    for item in project.get("resources") or []:
        task = tasks.get(item.get("task") or "") if isinstance(item, dict) else None
        if task is not None and isinstance(item.get("id"), str):
            served[item["id"]] = task
    return served


def _plan() -> m.Plan:
    stored = store().get("plan", "current")
    return m.Plan.model_validate(stored) if stored else m.Plan(handover=_now())


def _matches(data: dict, unit: str, inspection: str) -> bool:
    named = _norm(data.get("inspection"))
    return _unit(data.get("unit")) == _unit(unit) and bool(named) and (inspection in named or named in inspection)


def _inspection_name(requires: str, unit: str) -> str:
    """'Rough plumbing 2A' names the inspection and the unit; drop the unit to get the inspection."""
    name, unit = _norm(requires), _norm(unit)
    return name[: -len(unit) - 1] if unit and name.endswith(" " + unit) else name


def _unit(value: object) -> str:
    return re.sub(r"^unit\s+", "", _norm(value)).upper()


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _has_word(word: str, text: str) -> bool:
    return bool(word) and re.search(rf"(?<![a-z0-9]){re.escape(_norm(word))}(?![a-z0-9])", _norm(text)) is not None


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _stamp(value: datetime | None) -> str:
    moment = _utc(value)
    return moment.strftime("%Y-%m-%d %H:%M UTC") if moment else "an unknown time"


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)
