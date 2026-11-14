"""One clarifying question when a message names work, a delivery or equipment the project lists do not know.

Everything here is decided by code: which events qualify (the stored reason of the not understood fact), which
candidates are offered (the plan) and the wording (a fixed template). No model call.
"""
import hashlib
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core import models as m
from app.core.store import store
from app.live import directory
from app.live.delivery import DONE, SENDING_CHANNELS

log = logging.getLogger(__name__)

# The limits, in one place. A sender is asked once per event, never has more than MAX_OPEN questions open, and is
# not asked again while the last UNANSWERED_IN_A_ROW questions were each left open longer than ANSWER_WINDOW.
MAX_OPEN = 3
UNANSWERED_IN_A_ROW = 2
ANSWER_WINDOW = timedelta(hours=12)
MAX_CANDIDATES = 4
MAX_QUOTE_CHARS = 300

NONE_OF_THESE = "None of these"
DEFAULT_SITE_TIMEZONE = "Europe/Berlin"
RETRY = {"failed", "queued"}

INVALID = "answer invalid after one repair: "
# The exact validation errors of the extraction for a statement that names no known task, unit or resource. Any
# other error means the answer was wrong in a way a reply about names cannot fix.
REASON = re.compile(
    r"^fact \d+: type (?:(?P<work>work_planned|work_started) needs unit or task"
    r"|(?P<delivery>delivery_planned|delivery_actual) needs item"
    r"|(?P<equipment>equipment_planned|equipment_actual) needs item)$")

TEMPLATES = {
    "work": 'Which task do you mean by "{quote}"? These are the tasks of {crew} on {day}. '
            "If none of them fits, choose None of these.",
    "delivery": 'Which delivery do you mean by "{quote}"? These are the deliveries planned for {day}. '
                "If none of them fits, choose None of these.",
    "equipment": 'Which equipment do you mean by "{quote}"? This is the equipment planned for {day}. '
                 "If none of it fits, choose None of these.",
}


def _digest(event_id: str) -> str:
    return hashlib.sha256(event_id.encode()).hexdigest()[:24]


def message_id(event_id: str) -> str:
    return f"o-clarify-{_digest(event_id)}"


def waiting_id(event_id: str) -> str:
    return f"w-clarify-{_digest(event_id)}"


def answer_entry_id(event_id: str) -> str:
    return f"r-clarify-{_digest(event_id)}-answer"


def _site_zone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("SITE_TIMEZONE") or DEFAULT_SITE_TIMEZONE)


def _utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _day(value: object) -> date | None:
    moment = _utc(value)
    return moment.astimezone(_site_zone()).date() if moment else None


def _words(event: m.InboundEvent) -> str:
    return (event.transcript or event.text or "").strip()


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def kind_of(fact: m.Fact) -> str | None:
    """work, delivery or equipment when the fact is not understood only because it names something unknown."""
    data = fact.data or {}
    reason = data.get("reason")
    if data.get("not_understood") is not True or not isinstance(reason, str) or not reason.startswith(INVALID):
        return None
    errors = reason[len(INVALID):].split("; ")
    match = REASON.match(errors[0]) if len(errors) == 1 else None
    if match is None:
        return None
    return next(name for name in ("work", "delivery", "equipment") if match[name])


def _sender(event: m.InboundEvent) -> directory.Contact | None:
    """The person who wrote, if Aurora can answer them on the channel the message came from."""
    if event.channel not in SENDING_CHANNELS:
        return None
    contact = directory.lookup(event.sender or "") or directory.resolve(event.channel, event.sender)
    if contact is None or not contact.known or contact.kind != "person":
        return None
    # Telegram answers in the chat the message came from; mail and WhatsApp need an address for the name.
    if event.channel != "telegram" and not directory.reach(contact.name, event.channel):
        return None
    return contact


def _plan() -> m.Plan | None:
    raw = store().get("plan", "current")
    return m.Plan.model_validate(raw) if raw else None


def candidates(kind: str, crew: str | None, day: date) -> list[str]:
    """Button labels from the plan only: the crew's tasks that run on the day, or the resources planned for it."""
    plan = _plan()
    if plan is None:
        return []
    if kind == "work":
        if not crew:
            return []
        tasks = sorted((task for task in plan.tasks if task.crew == crew
                        and _day(task.start) <= day <= _day(task.end)), key=lambda task: (task.start, task.id))
        labels = [f"{task.id} {task.name}" for task in tasks]
    else:
        lines = sorted((line for line in plan.resources if line.kind == kind and _day(line.date) == day),
                       key=lambda line: (line.date, line.id))
        labels = [line.item for line in lines]
    return list(dict.fromkeys(labels))[:MAX_CANDIDATES]


def _questions_of(name: str) -> list[dict]:
    return [item for item in store().list("waiting")
            if item["id"].startswith("w-clarify-") and item.get("on") == name]


def _within_limits(name: str, own_id: str, now: datetime) -> bool:
    asked = [item for item in _questions_of(name) if item["id"] != own_id]
    if sum(1 for item in asked if item["status"] == "open") >= MAX_OPEN:
        return False
    recent = sorted(asked, key=lambda item: _utc(item["since"]))[-UNANSWERED_IN_A_ROW:]
    ignored = [item for item in recent
               if item["status"] == "open" and _utc(item["since"]) + ANSWER_WINDOW <= now]
    return len(ignored) < UNANSWERED_IN_A_ROW


def question(event: m.InboundEvent, facts: list[m.Fact]) -> m.OutboundMessage | None:
    """The one question for this event, or None when it does not qualify, was asked already or a limit holds."""
    own = [fact for fact in facts if fact.event_id == event.id]
    if len(own) != 1:
        return None
    kind = kind_of(own[0])
    quote = _words(event)
    if kind is None or not quote or len(quote) > MAX_QUOTE_CHARS:
        return None
    sent = store().get("outbox", message_id(event.id))
    if sent is not None and sent["status"] in DONE:
        return None
    contact = _sender(event)
    now = _utc(event.received_at)
    day = _day(event.sent_at)
    if contact is None or now is None or day is None:
        return None
    if not _within_limits(contact.name, waiting_id(event.id), now):
        log.info("clarify: no question for %s, the per sender limit holds", event.id)
        return None
    labels = candidates(kind, contact.crew, day)
    # With no candidate the only possible answer is None of these: it teaches nothing and costs the sender a
    # message, while the record already shows why the message was not understood.
    if not labels:
        return None
    text = TEMPLATES[kind].format(quote=quote, crew=contact.crew or "", day=day.isoformat())
    return m.OutboundMessage(
        id=message_id(event.id), channel=event.channel, to=contact.name, text=text,
        buttons=[*labels, NONE_OF_THESE], reason=f"Clarifying question: unknown {kind}",
        in_reply_to=event.id, created_at=event.received_at)


def _open(event: m.InboundEvent, message: m.OutboundMessage) -> None:
    quote = _words(event)
    short = quote if len(quote) <= 60 else quote[:57].rstrip() + "..."
    item = m.WaitingItem(id=waiting_id(event.id), on=message.to, what=f'Answer the question about "{short}"',
                         since=event.received_at, due=event.received_at + ANSWER_WINDOW,
                         source_event_ids=[event.id])
    if store().get("waiting", item.id) is None:
        store().put("waiting", item.id, item)


def _chosen(reply: str, buttons: list[str]) -> str | None:
    """The one label a reply names: the button text itself, or free text naming exactly one candidate."""
    said = _normal(reply)
    exact = [label for label in buttons if _normal(label) == said]
    if exact:
        return exact[0]
    named = []
    for label in buttons:
        if label == NONE_OF_THESE:
            continue
        # A task label starts with its id, which crews quote on its own.
        names = {label, label.split(" ", 1)[0]} if re.match(r"^\S+-\d+ ", label) else {label}
        if any(re.search(rf"(?<![\w-]){re.escape(_normal(name))}(?![\w-])", said) for name in names):
            named.append(label)
    return named[0] if len(named) == 1 else None


def _pressed_on(event: m.InboundEvent, sent: dict, asked_id: str) -> str | None:
    """The label of a button press on this very question, or None.

    A Telegram press carries the question it was on as its subject: the text as shown, which may have the
    recipient in front or be translated, so the asked quote inside it counts too. A plain message has no subject.
    """
    said = _normal(_words(event))
    label = next((label for label in sent.get("buttons") or [] if _normal(label) == said), None)
    subject = _normal(event.subject or "")
    if label is None or not subject:
        return None
    raw = store().get("events", asked_id)
    quote = _normal(_words(m.InboundEvent.model_validate(raw))) if raw else ""
    text = _normal(sent.get("text") or "")
    return label if (text and text in subject) or (quote and quote in subject) else None


def _answered(event: m.InboundEvent) -> bool:
    """Close the one open question this event answers. Returns whether it did."""
    reply = _words(event)
    contact = directory.lookup(event.sender or "") or directory.resolve(event.channel, event.sender)
    if not reply or contact is None or not contact.known:
        return False
    matches = []
    own = _questions_of(contact.name)
    # The superintendent answers for a crew that has not replied yet, but only by pressing a button on that crew's
    # question: free text from the superintendent is about their own work, and a task id in it is not an answer.
    supervising = "superintendent" in (contact.role or "").lower()
    others = [item for item in store().list("waiting")
              if supervising and item["id"].startswith("w-clarify-") and item not in own]
    for item in [*own, *others]:
        if item["status"] != "open" or event.id in item["source_event_ids"]:
            continue
        asked_id = item["source_event_ids"][0]
        sent = store().get("outbox", message_id(asked_id)) or {}
        if item in own:
            label = _chosen(reply, sent.get("buttons") or [])
        else:
            label = _pressed_on(event, sent, asked_id)
        if label is not None:
            matches.append((item, asked_id, label))
    if len(matches) > 1 and event.subject:
        # A button press carries the question it was on; keep the question whose quote it shows.
        asked = {asked_id: _words(m.InboundEvent.model_validate(store().get("events", asked_id)))
                 for _, asked_id, _ in matches if store().get("events", asked_id)}
        matches = [match for match in matches if asked.get(match[1]) and asked[match[1]] in event.subject]
    if len(matches) != 1:
        return False
    item, asked_id, label = matches[0]
    store().put("waiting", item["id"], {**item, "status": "done",
                                        "source_event_ids": [*item["source_event_ids"], event.id]})
    raw = store().get("events", asked_id)
    quote = _words(m.InboundEvent.model_validate(raw)) if raw else ""
    entry = m.RecordEntry(
        id=answer_entry_id(asked_id), at=event.received_at, kind="info", title="Clarifying question answered",
        detail=f'Asked which is meant by "{quote}". Answer: {label}.', actor=contact.name,
        source_event_ids=[asked_id, event.id],
        refs={"waiting": item["id"], "message": message_id(asked_id), "answer": label})
    store().put("record", entry.id, entry)
    return True


def _retries() -> list[m.OutboundMessage]:
    """A question whose send failed is offered again under the same id while its question is still open."""
    messages = []
    for sent in store().list("outbox"):
        if not sent["id"].startswith("o-clarify-") or sent["status"] not in RETRY:
            continue
        item = store().get("waiting", "w-clarify-" + sent["id"].removeprefix("o-clarify-"))
        if item is not None and item["status"] == "open":
            messages.append(m.OutboundMessage.model_validate(sent))
    return messages


def react(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.OutboundMessage]:
    """Called from outbox.react: close an answered question, else ask about this event; returns what to deliver."""
    if _answered(event):
        return _retries()
    message = question(event, facts)
    if message is None:
        return _retries()
    _open(event, message)
    return [message, *(retry for retry in _retries() if retry.id != message.id)]
