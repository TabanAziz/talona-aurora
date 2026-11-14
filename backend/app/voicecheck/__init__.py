"""Read a voice note back to its sender before anything is taken from it.

Speech to text can be wrong with full confidence (heavy site noise turned "3B" into "3D" for two different
recognisers), so only the sender can catch it. The pipeline calls `screen(event)` right after transcription. A
voice note is held: Aurora answers the sender with the text it heard, a waiting item shows the open check, and no
area sees the note. The sender's answer releases it exactly once, either as heard (Confirm) or, after Correct it,
with the text they type next. Everything here is decided by code: no model call.
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

from app.core import models as m
from app.core import pipeline
from app.core.registry import area, is_mock
from app.core.store import store
from app.live import directory
from app.live.delivery import DONE, SENDING_CHANNELS, deliver

log = logging.getLogger(__name__)

COLLECTION = "voicechecks"
CONFIRM = "Confirm"
CORRECT = "Correct it"
ANSWER_WINDOW = timedelta(hours=12)
# A longer read-back would not fit one chat message, and a cut quote would ask the sender to confirm text they
# cannot see.
MAX_HEARD_CHARS = 3000
MAX_SHORT_CHARS = 60
RETRY = {"failed", "queued"}
# A channel that is down must not cost every later ingest a send timeout.
RETRY_EVERY = timedelta(minutes=5)
# What a release may write. The outbox is left out on purpose: a message that went out cannot be taken back, and
# deleting its row would send it a second time on the retry.
ROLLBACK = ("events", "facts", "record", "waiting", "flags", "proposals", "diffs", "answers", COLLECTION)

READ_BACK = ('I heard your voice note as: "{heard}" If that is right, press Confirm. If not, press Correct it and '
             "then send the full corrected text. Nothing from this note is used until you answer.")
ASK_TEXT = 'Please send the full corrected text of your voice note now. I heard: "{heard}"'


def _digest(event_id: str) -> str:
    return hashlib.sha256(event_id.encode()).hexdigest()[:24]


def message_id(event_id: str) -> str:
    return f"o-voicecheck-{_digest(event_id)}"


def ask_id(event_id: str) -> str:
    return f"o-voicecheck-{_digest(event_id)}-text"


def waiting_id(event_id: str) -> str:
    return f"w-voicecheck-{_digest(event_id)}"


def answer_entry_id(event_id: str) -> str:
    return f"r-voicecheck-{_digest(event_id)}-answer"


def _doc_id(collection: str, doc: dict) -> str:
    return doc["event_id"] if collection == COLLECTION else doc["id"]


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", text.casefold()).split())


def _sender_key(event: m.InboundEvent) -> str:
    return f"{event.channel}:{' '.join((event.sender or '').split()).casefold()}"


def _is_voice_note(event: m.InboundEvent) -> bool:
    return any(attachment.kind == "audio" for attachment in event.attachments)


def _recipient(event: m.InboundEvent) -> str | None:
    """Who the read-back goes to, or None when Aurora cannot answer the sender on the channel the note came from."""
    if event.channel not in SENDING_CHANNELS or not (event.sender or "").strip():
        return None
    contact = directory.lookup(event.sender) or directory.resolve(event.channel, event.sender)
    name = contact.name if contact is not None and contact.known else None
    # Telegram answers in the chat the note came from; mail and WhatsApp need an address for a known name, so an
    # address never has to be written into the outbox.
    if event.channel == "telegram":
        return name or event.sender.strip()
    return name if name and directory.reach(name, event.channel) else None


def _deliver(message: m.OutboundMessage, event_id: str) -> m.OutboundMessage:
    guest = area("guest")
    with guest.delivery_scope([event_id]):
        return deliver(guest.bind_delivery(message, [event_id]))


def _sent(sent_id: str) -> list[m.OutboundMessage]:
    sent = store().get("outbox", sent_id)
    return [m.OutboundMessage.model_validate(sent)] if sent else []


def _hold(event: m.InboundEvent, to: str) -> m.IngestResult:
    heard = (event.transcript or "").strip()
    short = heard if len(heard) <= MAX_SHORT_CHARS else heard[:MAX_SHORT_CHARS - 3].rstrip() + "..."
    message = m.OutboundMessage(
        id=message_id(event.id), channel=event.channel, to=to, text=READ_BACK.format(heard=heard),
        buttons=[CONFIRM, CORRECT], reason="Read-back of a voice note before it is used", in_reply_to=event.id,
        created_at=event.received_at)
    # The waiting text must not start with "Confirm" or "Read back": the outbox reads those as drawing checks.
    item = m.WaitingItem(id=waiting_id(event.id), on=to, what=f'Check the text of the voice note: "{short}"',
                         since=event.received_at, due=event.received_at + ANSWER_WINDOW, source_event_ids=[event.id])
    store().put("waiting", item.id, item)
    store().put(COLLECTION, event.id, {
        "event_id": event.id, "sender": _sender_key(event), "to": to, "channel": event.channel, "heard": heard,
        "status": "open", "corrected": None, "answer_event_id": None, "message_id": message.id,
        "waiting_id": item.id,
    })
    sent = _deliver(message, event.id)
    log.info("voicecheck: %s held until %s answers the read-back (%s)", event.id, to, sent.status)
    return m.IngestResult(event_id=event.id, outbox=[sent])


def _waiting_checks(event: m.InboundEvent) -> list[dict]:
    """The sender's unanswered checks whose read-back reached them, newest first."""
    key = _sender_key(event)
    checks = [check for check in store().list(COLLECTION)
              if check["sender"] == key and check["status"] in ("open", "awaiting_text")]
    delivered = [check for check in checks
                 if (store().get("outbox", check["message_id"]) or {}).get("status") in DONE]
    return list(reversed(delivered))


def _quoted(event: m.InboundEvent) -> list[dict]:
    """Every check whose read-back this button press is on, newest first: the press carries the read-back as its
    subject, and the read-back quotes the heard text."""
    said = _plain(event.subject or "")
    return list(reversed([check for check in store().list(COLLECTION)
                          if said and _plain(check["heard"]) in said]))


def _answer(event: m.InboundEvent) -> tuple[str, dict | None] | None:
    """What this event does to a read-back: ("confirm" | "ask_text" | "correct", check), ("ignore", None) for a press
    that must not count, or None when the event is not about a read-back at all."""
    text = (event.text or "").strip()
    if _is_voice_note(event) or not text:
        return None
    said = _plain(text)
    labels = {_plain(CONFIRM): "confirm", _plain(CORRECT): "ask_text"}
    if event.subject is not None:
        if said not in labels:
            return None
        quoted = _quoted(event)
        if not quoted:
            return None
        # A press counts only from the person who spoke and only once. Any other press on a read-back is dropped,
        # not passed on: its subject holds the unconfirmed text, which extraction would read as this message.
        mine = [check for check in quoted if check["sender"] == _sender_key(event)
                and check["status"] in ("open", "awaiting_text")]
        return (labels[said], mine[0]) if mine else ("ignore", None)
    checks = _waiting_checks(event)
    if not checks:
        return None
    if said in labels:
        # A typed label, or a press that arrives without the message it was on (a guest's private chat).
        return labels[said], checks[0]
    # Only after Correct it is typed text taken as the note's text: before that the sender may well write about
    # something else, and that message must reach the record as itself.
    awaiting = [check for check in checks if check["status"] == "awaiting_text"]
    return ("correct", awaiting[0]) if awaiting else None


def _ask_text(event: m.InboundEvent, check: dict) -> m.IngestResult:
    store().put(COLLECTION, check["event_id"], {**check, "status": "awaiting_text"})
    message = m.OutboundMessage(
        id=ask_id(check["event_id"]), channel=check["channel"], to=check["to"],
        text=ASK_TEXT.format(heard=check["heard"]), reason="Corrected text of a voice note asked for",
        in_reply_to=check["event_id"], created_at=event.received_at)
    return m.IngestResult(event_id=event.id, outbox=[_deliver(message, check["event_id"])])


def _release(event: m.InboundEvent, kind: str, check: dict) -> m.IngestResult:
    s = store()
    held_id = check["event_id"]
    raw_event = s.get("events", held_id)
    raw_item = s.get("waiting", check["waiting_id"])
    corrected = (event.text or "").strip() if kind == "correct" else None
    done = {**check, "status": "corrected" if corrected else "confirmed", "corrected": corrected,
            "answer_event_id": event.id}
    if corrected:
        title = f"Voice note corrected by {check['to']}"
        detail = f'Heard: "{check["heard"]}" Corrected by the sender to: "{corrected}"'
    else:
        title = f"Voice note confirmed by {check['to']}"
        detail = f'Heard: "{check["heard"]}" Confirmed by the sender.'
    entry = m.RecordEntry(
        id=answer_entry_id(held_id), at=event.received_at, kind="info", title=title, detail=detail,
        actor=check["to"], source_event_ids=[held_id, event.id],
        refs={"waiting": check["waiting_id"], "message": check["message_id"], "voice_note": held_id})
    before = {name: {_doc_id(name, doc): doc for doc in s.list(name)} for name in ROLLBACK}
    s.put(COLLECTION, held_id, done)
    if raw_item is not None:
        s.put("waiting", raw_item["id"], {**raw_item, "status": "done",
                                          "source_event_ids": [*raw_item["source_event_ids"], event.id]})
    if corrected and raw_event is not None:
        s.put("events", held_id, {**raw_event, "transcript": corrected})
    s.put("record", entry.id, entry)
    try:
        released = pipeline.reprocess(held_id)
    except Exception:
        # Back to the state before the answer, including what the areas wrote before the failure, so the note is
        # still held and a retry of this answer releases it instead of finding it done.
        for name, docs in before.items():
            for doc in s.list(name):
                if _doc_id(name, doc) not in docs:
                    s.delete(name, _doc_id(name, doc))
            for key, doc in docs.items():
                s.put(name, key, doc)
        raise
    log.info("voicecheck: %s released by %s as %s", held_id, event.id, done["status"])
    if released is None:
        return m.IngestResult(event_id=event.id, record=[entry])
    return released.model_copy(update={"event_id": event.id, "record": [entry, *released.record]})


def _retry_failed() -> None:
    """A read-back whose send failed is sent again under the same id while its note is still held, at most once
    every RETRY_EVERY."""
    now = datetime.now(timezone.utc)
    for check in store().list(COLLECTION):
        if check["status"] not in ("open", "awaiting_text"):
            continue
        tried = datetime.fromisoformat(check["retried_at"]) if check.get("retried_at") else None
        if tried is not None and now - tried < RETRY_EVERY:
            continue
        failed = [sent for sent in (store().get("outbox", sent_id)
                                    for sent_id in (check["message_id"], ask_id(check["event_id"])))
                  if sent is not None and sent["status"] in RETRY]
        if not failed:
            continue
        store().put(COLLECTION, check["event_id"], {**check, "retried_at": now.isoformat()})
        for sent in failed:
            _deliver(m.OutboundMessage.model_validate(sent), check["event_id"])


def screen(event: m.InboundEvent) -> m.IngestResult | None:
    """Called by the pipeline after transcription. Returns the result of this event when the read-back handled it
    (a note held, an answer to a read-back), or None to let the event through as usual."""
    # A transcript from the voice mock is the scenario's own text, not something a recogniser heard.
    if is_mock("voice"):
        return None
    _retry_failed()
    check = store().get(COLLECTION, event.id)
    if check is not None:
        if check["status"] in ("open", "awaiting_text"):
            return m.IngestResult(event_id=event.id, outbox=_sent(check["message_id"]))
        return None
    if any(check["answer_event_id"] == event.id for check in store().list(COLLECTION)):
        # An answer run again (a reprocess) is not a message of its own: its text is already in the note.
        return m.IngestResult(event_id=event.id)
    answer = _answer(event)
    if answer is not None:
        kind, target = answer
        if target is None:
            return m.IngestResult(event_id=event.id)
        return _ask_text(event, target) if kind == "ask_text" else _release(event, kind, target)
    heard = (event.transcript or "").strip()
    if not _is_voice_note(event) or not heard:
        return None
    if len(heard) > MAX_HEARD_CHARS:
        log.warning("voicecheck: %s not read back, its transcript is longer than %d characters", event.id,
                    MAX_HEARD_CHARS)
        return None
    to = _recipient(event)
    if to is None:
        log.info("voicecheck: %s not read back, Aurora cannot answer the sender on %s", event.id, event.channel)
        return None
    return _hold(event, to)
