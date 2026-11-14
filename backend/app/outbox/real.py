"""Revision notices, one reminder on conflicting work, an escalation ladder for silent crews, the read-back that
checks a crew understood a change, and sourced crew answers."""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from app import dailyreport, readback, rework
from app.core import config, models as m
from app.core.registry import area
from app.core.store import store
from app.live import directory
from app.live.delivery import deliver as _deliver
# On its own line: the shared import line above changes with every hook that lands.
from app import clarify

# How long before the affected work starts each step fires while the crew has not confirmed. Step 1 is the reminder
# sent when conflicting work is announced.
LADDER = {2: timedelta(hours=12), 3: timedelta(hours=4)}
CONFIRMATION = re.compile(r"^Confirm (?P<sheet>.+) Rev (?P<revision>\S+)$")
READ_BACK = re.compile(r"^Read back (?P<sheet>.+) Rev (?P<revision>\S+)$")
RETRY = {"failed", "queued"}
DELIVERED = {"sent", "simulated"}
SUPERINTENDENT = "Superintendent"


def _id(kind: str, *values: str) -> str:
    return f"o-{kind}-" + hashlib.sha256("\0".join(values).encode()).hexdigest()[:24]


def _when(value: object) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _stamp(value: object) -> str:
    moment = _when(value)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if moment else "unknown time"


def _pending(sheet: str, revision: str) -> list[dict]:
    sources = {fact["event_id"] for fact in store().list("facts")
               if fact["type"] == "drawing_revision" and fact["data"].get("sheet") == sheet
               and fact["data"].get("revision") == revision}
    return [item for item in store().list("waiting") if item["status"] == "open"
            and item["what"] == f"Confirm {sheet} Rev {revision}"
            and sources.intersection(item["source_event_ids"])]


def _current(sheet: str, revision: str) -> bool:
    lookup = getattr(area("record"), "current_revision", None)
    if lookup is None:
        return True
    latest = lookup(sheet)
    return latest is not None and latest.data.get("revision") == revision


def _drawing(sheet: str, revision: str) -> m.DrawingDiff | None:
    return next((m.DrawingDiff.model_validate(raw) for raw in reversed(store().list("diffs"))
                 if raw["sheet"] == sheet and raw["to_rev"] == revision), None)


def _media(diff: m.DrawingDiff | None) -> str | None:
    if diff is None:
        return None
    # The drawing renderer writes a crop alongside the overlay, under the public files root.
    if diff.overlay_url.startswith("/media/files/"):
        for name in ("crop.png", "crop.svg"):
            url = str(PurePosixPath(diff.overlay_url).with_name(name))
            base = (config.data_dir() / "files").resolve()
            target = (base / url.removeprefix("/media/files/")).resolve()
            if base in target.parents and target.is_file():
                return url
    return diff.overlay_url


def _superintendent() -> str:
    return next((person.name for person in directory.people() if (person.role or "").lower() == "superintendent"),
                SUPERINTENDENT)


def _second_attempt(item: dict, original: dict, now: datetime) -> m.OutboundMessage | None:
    crew = item["on"]
    # A machine has only its queue, so the ladder goes from its notice straight to the superintendent.
    if original["channel"] == "machine":
        return None
    channel = "email" if original["channel"] == "telegram" else "telegram"
    # Telegram reaches anyone through the group chat; email needs an address, and a send that can only fail
    # would be retried on every event without reaching anyone.
    if channel == "email" and not directory.reach(crew, channel):
        return None
    return m.OutboundMessage(
        id=f"o-esc-{item['id']}-2", channel=channel, to=crew,
        text=f"Second attempt, your confirmation is still missing. {original['text']}",
        media_url=original.get("media_url"), buttons=["Confirmed"],
        reason="Escalation step 2: second channel", created_at=now)


def _tell_superintendent(item: dict, sheet: str, revision: str, due: datetime, now: datetime) -> m.OutboundMessage:
    crew = item["on"]
    ids = [_id("revision", sheet, revision, crew), _id("reminder", sheet, revision, crew), f"o-esc-{item['id']}-2"]
    attempts = [sent for sent in (store().get("outbox", i) for i in ids) if sent is not None]
    tried = "; ".join(f"{sent['channel']} {_stamp(sent['created_at'])} ({sent['status']})" for sent in attempts)
    text = (f"{crew} has not confirmed {sheet} Rev {revision}. Their work starts {_stamp(due)}. "
            f"Sent so far: {tried or 'nothing'}.")
    if not any(sent["id"] == ids[2] for sent in attempts):
        text += f" No second channel is known for {crew}."
    open_flags = [flag for flag in store().list("flags") if flag.get("status") == "open"
                  and flag.get("type") in {"stale_drawing", "unacknowledged_change"}
                  and (flag.get("affected") or {}).get("sheet") == sheet
                  and (flag.get("affected") or {}).get("crew") == crew]
    if open_flags:
        text += f" Open flag for the same work: {open_flags[0]['title']}."
    return m.OutboundMessage(id=f"o-esc-{item['id']}-3", channel="telegram", to=_superintendent(), text=text,
                             reason="Escalation step 3: superintendent", created_at=now)


def _ladder(now: datetime) -> list[m.OutboundMessage]:
    """The next due step for every open change confirmation, read from the store as it was before this event.

    There is no timer: the clock is the event being ingested, so replays and tests stay deterministic. One new step
    per item and event keeps the second channel and the superintendent from hearing about it in the same instant.
    """
    messages = []
    for item in store().list("waiting"):
        match = CONFIRMATION.match(item.get("what") or "")
        due = _when(item.get("due")) if item.get("due") else None
        if item.get("status") != "open" or match is None or due is None or now >= due:
            continue
        sheet, revision = match["sheet"], match["revision"]
        original = store().get("outbox", _id("revision", sheet, revision, item["on"]))
        if original is None:
            continue
        for step, before in LADDER.items():
            sent = store().get("outbox", f"o-esc-{item['id']}-{step}")
            if sent is not None:
                if sent["status"] in RETRY:
                    messages.append(area("guest").bind_delivery(m.OutboundMessage.model_validate(sent), item["source_event_ids"]))
                continue
            if now < due - before:
                break
            message = (_second_attempt(item, original, now) if step == 2
                       else _tell_superintendent(item, sheet, revision, due, now))
            if message is not None:
                messages.append(area("guest").bind_delivery(message, item["source_event_ids"]))
                break
    return messages


def _read_back_id(crew: str, sheet: str, revision: str) -> str:
    digest = hashlib.sha256("\0".join((crew, sheet, revision)).encode()).hexdigest()[:24]
    return f"w-readback-{digest}"


def _name(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _confirmation_due(crew: str, sheet: str, revision: str) -> datetime | None:
    """The confirmation item was closed by the record just before this step runs, so read it whatever its status."""
    for item in store().list("waiting"):
        if item["on"] == crew and item["what"] == f"Confirm {sheet} Rev {revision}" and item.get("due"):
            return _when(item["due"])
    return None


def _expected(diff: m.DrawingDiff) -> str | None:
    # A bare reply is judged in code, so this reads the expected move without a model call.
    return readback.judge(diff, "").expected


def _reply(event: m.InboundEvent) -> str:
    return (event.transcript or event.text or "").strip()


def _crew_of(event: m.InboundEvent) -> str | None:
    guest_crew = area("guest").crew(event.id)
    if guest_crew is not None:
        return guest_crew
    contact = directory.lookup(event.sender or "") or directory.resolve(event.channel, event.sender)
    if contact is None or not contact.known:
        return None
    return contact.name if contact.kind == "crew" else contact.crew


def _unit(diff: m.DrawingDiff) -> str:
    project = store().get("project", "current") or {}
    text = " ".join([diff.summary or ""] + [region.label or "" for region in diff.regions])
    return next((unit for unit in project.get("units") or [] if isinstance(unit, str)
                 and re.search(rf"(?<![A-Za-z0-9]){re.escape(unit)}(?![A-Za-z0-9])", text)), "")


def _question(item_id: str, crew: str, diff: m.DrawingDiff, asked: str, event: m.InboundEvent) -> m.OutboundMessage:
    return m.OutboundMessage(
        id=f"o-readback-{item_id}-question", channel="telegram", to=crew,
        text=f"{asked} Please reply with the change in your own words.", media_url=_media(diff),
        reason="Read-back question after a bare confirmation", in_reply_to=event.id, created_at=event.received_at)


def _thanks(item_id: str, crew: str, diff: m.DrawingDiff, expected: str | None,
           event: m.InboundEvent) -> m.OutboundMessage:
    return m.OutboundMessage(
        id=f"o-readback-{item_id}-thanks", channel="telegram", to=crew,
        text=f"Thanks, that matches: {expected or 'the change is understood'}. {diff.sheet} Rev {diff.to_rev}.",
        reason="Read-back matched", in_reply_to=event.id, created_at=event.received_at)


def _correction(item_id: str, crew: str, diff: m.DrawingDiff, expected: str | None, said: str | None,
                number: int, event: m.InboundEvent, now: datetime) -> m.OutboundMessage:
    return m.OutboundMessage(
        id=f"o-readback-{item_id}-correction-{number}", channel="telegram", to=crew,
        text=f"{diff.sheet} Rev {diff.to_rev}: it moves {expected or 'differently'}, not {said or 'that'}. "
             f"Look at the marked plan and reply again.",
        media_url=_media(diff), reason="Read-back did not match the change",
        in_reply_to=event.id, created_at=now)


def _corrections(item_id: str) -> int:
    """Only corrections the crew actually received count: a send that failed is offered again as the same one."""
    prefix = f"o-readback-{item_id}-correction-"
    return sum(1 for sent in store().list("outbox")
               if sent["id"].startswith(prefix) and sent["status"] in DELIVERED)


def _read_back_retries() -> list[m.OutboundMessage]:
    """Like the ladder, a failed read-back message is offered again on the next event under the same id."""
    return [area("guest").bind_delivery(m.OutboundMessage.model_validate(sent), []) for sent in store().list("outbox")
            if sent["id"].startswith("o-readback-") and sent["status"] in RETRY]


def _read_back_escalation(item: dict, diff: m.DrawingDiff, expected: str | None, said: str | None,
                         now: datetime) -> m.OutboundMessage:
    unit = _unit(diff)
    events = ", ".join(dict.fromkeys(item["source_event_ids"]))
    return m.OutboundMessage(
        id=f"o-readback-{item['id']}-super", channel="telegram", to=_superintendent(),
        text=(f"{item['on']} confirmed {diff.sheet} Rev {diff.to_rev} but has not shown it understood the change"
              f"{f' for unit {unit}' if unit else ''}. Expected: {expected or 'no measurable move'}. "
              f"Said: {said or 'no answer'}. Events: {events}."),
        reason="Read-back still not understood before work starts", created_at=now)


def _last_answer(item: dict) -> str | None:
    for event_id in reversed(item["source_event_ids"][1:]):
        raw = store().get("events", event_id)
        if raw is None:
            continue
        text = _reply(m.InboundEvent.model_validate(raw))
        if text:
            return text
    return None


def _close_read_back(item: dict, event: m.InboundEvent) -> None:
    sources = item["source_event_ids"]
    store().put("waiting", item["id"], {**item, "status": "done",
                                        "source_event_ids": [*sources, event.id] if event.id not in sources else sources})


def _read_back(event: m.InboundEvent, facts: list[m.Fact], now: datetime) -> list[m.OutboundMessage]:
    """The confirmation the record tracks is "received"; this is "understood", a second waiting item per crew and
    change. The question is asked at most once, and the read-back never reopens the confirmation or a flag."""
    messages: list[m.OutboundMessage] = []
    for fact in facts:
        if fact.event_id != event.id or fact.type != "acknowledgement":
            continue
        sheet, revision, crew = (_name(fact.data.get(key)) for key in ("sheet", "revision", "crew"))
        if not sheet or not revision or not crew:
            continue
        diff = _drawing(sheet, revision)
        asked = readback.question(diff) if diff is not None else None
        if diff is None or asked is None:
            continue
        item_id = _read_back_id(crew, sheet, revision)
        item = store().get("waiting", item_id)
        if item is not None and item["status"] == "done":
            continue
        verdict = readback.judge(diff, _reply(event))
        if verdict.verdict == "match":
            messages.append(_thanks(item_id, crew, diff, verdict.expected, event))
            if item is not None:
                _close_read_back(item, event)
            continue
        if item is None:
            waiting = m.WaitingItem(
                id=item_id, on=crew, what=f"Read back {sheet} Rev {revision}", since=event.received_at,
                due=_confirmation_due(crew, sheet, revision), source_event_ids=[event.id])
            store().put("waiting", waiting.id, waiting)
            item = store().get("waiting", item_id)
        if verdict.verdict == "mismatch":
            number = _corrections(item_id) + 1
            messages.append(_correction(item_id, crew, diff, verdict.expected, verdict.said, number, event, now))
            if number >= 2 and store().get("outbox", f"o-readback-{item_id}-super") is None:
                messages.append(_read_back_escalation(item, diff, verdict.expected, verdict.said, now))
        else:
            sent = store().get("outbox", f"o-readback-{item_id}-question")
            if sent is None or sent["status"] in RETRY:
                messages.append(_question(item_id, crew, diff, asked, event))

    crew = _crew_of(event)
    other_fact = any(fact.event_id == event.id and fact.type not in {"acknowledgement", "other"} for fact in facts)
    if crew is None or other_fact:
        return messages
    for item in store().list("waiting"):
        match = READ_BACK.match(item.get("what") or "")
        if item["status"] != "open" or item.get("on") != crew or match is None:
            continue
        if event.id in item["source_event_ids"]:
            continue
        diff = _drawing(match["sheet"], match["revision"])
        reply = _reply(event)
        if diff is None or not reply:
            continue
        verdict = readback.judge(diff, reply)
        item = {**item, "source_event_ids": [*item["source_event_ids"], event.id]}
        if verdict.verdict == "match":
            item["status"] = "done"
            messages.append(_thanks(item["id"], crew, diff, verdict.expected, event))
        elif verdict.verdict == "mismatch":
            number = _corrections(item["id"]) + 1
            messages.append(_correction(item["id"], crew, diff, verdict.expected, verdict.said, number, event, now))
            if number >= 2 and store().get("outbox", f"o-readback-{item['id']}-super") is None:
                messages.append(_read_back_escalation(item, diff, verdict.expected, verdict.said, now))
        store().put("waiting", item["id"], item)
    return messages


def _read_back_ladder(event: m.InboundEvent, now: datetime) -> list[m.OutboundMessage]:
    """A read-back still open when the confirmation ladder reaches its last step goes to the superintendent once."""
    messages = []
    for item in store().list("waiting"):
        match = READ_BACK.match(item.get("what") or "")
        due = _when(item.get("due")) if item.get("due") else None
        if item["status"] != "open" or match is None or due is None or now < due - LADDER[3]:
            continue
        # A question asked by this very event must not escalate in the same instant.
        if event.id in item["source_event_ids"]:
            continue
        sent = store().get("outbox", f"o-readback-{item['id']}-super")
        if sent is not None:
            if sent["status"] in RETRY:
                messages.append(area("guest").bind_delivery(m.OutboundMessage.model_validate(sent), item["source_event_ids"]))
            continue
        diff = _drawing(match["sheet"], match["revision"])
        if diff is None:
            continue
        messages.append(area("guest").bind_delivery(
            _read_back_escalation(item, diff, _expected(diff), _last_answer(item), now), item["source_event_ids"]))
    return messages


def react(event: m.InboundEvent, facts: list[m.Fact], flags: list[m.Flag], answer: m.Answer | None) -> list[m.OutboundMessage]:
    pending: dict[str, m.OutboundMessage] = {}

    def add(message):
        existing = store().get("outbox", message.id)
        if existing is None or existing["status"] in RETRY:
            pending[message.id] = area("guest").bind_delivery(message, [event.id])

    now = _when(event.received_at)
    for message in _ladder(now) if now else []:
        add(message)
    for message in area("followup").react(event, facts):
        add(message)
    for message in _read_back(event, facts, now) if now else []:
        add(message)
    for message in clarify.react(event, facts) if now else []:
        add(message)
    area("names").learn()
    for message in _read_back_retries() if now else []:
        add(message)
    dailyreport.send(event)
    for message in _read_back_ladder(event, now) if now else []:
        add(message)
    for message in rework.handle(event, facts):
        add(message)

    # A machine's confirmation item gets its notice on the machine channel below, never a crew message.
    machines = {machine.id for machine in area("machine").machines()}
    for fact in facts:
        if fact.event_id != event.id or fact.type != "drawing_revision":
            continue
        sheet, revision = fact.data.get("sheet"), fact.data.get("revision")
        if not isinstance(sheet, str) or not isinstance(revision, str) or not _current(sheet, revision):
            continue
        diff = _drawing(sheet, revision)
        for waiting in _pending(sheet, revision):
            crew = waiting["on"]
            if crew in machines:
                continue
            text = f"{sheet} Rev {revision} is current. "
            if diff and diff.summary:
                text += diff.summary + " "
            text += f"Please confirm you have Rev {revision} before starting the affected work."
            add(m.OutboundMessage(id=_id("revision", sheet, revision, crew), channel="telegram", to=crew,
                text=text, media_url=_media(diff), buttons=["Confirmed"], reason="Drawing revision needs crew confirmation",
                created_at=event.received_at))
    # Not bound to a guest route: a machine notice stays in the machine's queue whoever brought the revision.
    for message in area("machine").react(event, facts):
        existing = store().get("outbox", message.id)
        if existing is None or existing["status"] in RETRY:
            pending[message.id] = message

    for flag in flags:
        if flag.status != "open" or flag.type not in {"stale_drawing", "unacknowledged_change"}:
            continue
        sheet, revision, crew = (flag.affected.get(key, "") for key in ("sheet", "revision", "crew"))
        if not all((sheet, revision, crew)) or not _current(sheet, revision):
            continue
        if not any(item["on"] == crew for item in _pending(sheet, revision)):
            continue
        original = _id("revision", sheet, revision, crew)
        if store().get("outbox", original) is None:
            continue
        add(m.OutboundMessage(id=_id("reminder", sheet, revision, crew), channel="telegram", to=crew,
            text=f"Reminder: confirm {sheet} Rev {revision} before starting the affected work. {flag.summary}",
            media_url=_media(_drawing(sheet, revision)), buttons=["Confirmed"],
            reason="One reminder after work was announced without confirmation", created_at=event.received_at))

    if answer is not None and answer.event_id == event.id:
        text = answer.text
        for source in answer.sources:
            text += f"\nSource: {source.sender}, {source.at.isoformat()}: {source.quote}"
        add(m.OutboundMessage(id=_id("answer", answer.id), channel=event.channel, to=event.sender,
            text=text, reason="Answer to crew question", in_reply_to=event.id, created_at=answer.created_at))
    return [_deliver(message) for message in pending.values()]
