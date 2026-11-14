"""Names learned from a clarifying answer: the words a crew uses for a task, unit or item of the project.

The record is the only place a learned name lives: one entry of kind info titled "Learned name", with `refs`
holding the name (the quoted words of the message, normalized) and the target (task, unit or item). `known()`
reads them back for the extraction prompt; `learn()` turns each answered clarification into one name and runs the
message that was not understood through the pipeline again, so it finally becomes the facts it always stated.
"""
import hashlib
import logging
import re
import threading

from app.core import models as m
from app.core import pipeline
from app.core.store import store
from app.live import directory

log = logging.getLogger(__name__)

TITLE = "Learned name"
ANSWER_TITLE = "Clarifying question answered"
NONE_OF_THESE = "None of these"
UNRESOLVED_TITLE = "Message stays not understood"
TARGETS = ("task", "unit", "item")
# Each reprocess is a model extraction under the pipeline lock; a message the name does not help must not cost one
# on every later event.
MAX_ATTEMPTS = 2
ATTEMPTS = "reprocess_attempts"
_learning = threading.local()


class _StillUnclear(Exception):
    """The reprocess ran, but its extraction still calls the message not understood; the text is the reason."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def entry_id(asked_event_id: str) -> str:
    return f"r-name-{_digest(asked_event_id)}"


def unresolved_id(asked_event_id: str) -> str:
    return f"r-name-unresolved-{_digest(asked_event_id)}"


def known() -> list[dict]:
    """The learned names, read from the record and nowhere else."""
    names = []
    for entry in store().list("record"):
        if entry.get("title") != TITLE:
            continue
        refs = entry.get("refs") or {}
        name = refs.get("name")
        target = next((key for key in TARGETS if refs.get(key)), None)
        if not isinstance(name, str) or not name or target is None:
            continue
        names.append({"name": name, target: refs[target], "at": entry.get("at")})
    return names


def learn() -> list[m.RecordEntry]:
    """One learned name per answered clarification. Idempotent, and a name whose message cannot be reprocessed is
    taken back so a later event can try again instead of leaving a name nobody could apply. The answer entry counts
    the attempts in `refs.reprocess_attempts`; after the second failed one the record says the message stays not
    understood and it is never run again for that answer."""
    if getattr(_learning, "active", False):
        # The reprocess runs the pipeline again, which reaches this hook; the outer call finishes the work.
        return []
    _learning.active = True
    try:
        return _learn_pending()
    finally:
        _learning.active = False


def _learn_pending() -> list[m.RecordEntry]:
    written = []
    for answer in store().list("record"):
        if answer.get("title") != ANSWER_TITLE:
            continue
        asked_id = (answer.get("source_event_ids") or [None])[0]
        if not asked_id or store().get("record", entry_id(asked_id)) is not None:
            continue
        if _attempts(answer) >= MAX_ATTEMPTS or store().get("record", unresolved_id(asked_id)) is not None:
            continue
        entry = _learned(answer, asked_id)
        if entry is None:
            continue
        attempts = _attempts(answer) + 1
        # Counted before the reprocess, so an attempt that crashes the process still counts.
        store().put("record", answer["id"], {**answer, "refs": {**(answer.get("refs") or {}),
                                                                 ATTEMPTS: str(attempts)}})
        store().put("record", entry.id, entry)
        try:
            result = pipeline.reprocess(asked_id)
            unclear = [fact for fact in (result.facts if result is not None else [])
                       if fact.data.get("not_understood") is True]
            if unclear:
                # Extraction keeps an unavailable model as a not understood fact instead of raising.
                raise _StillUnclear(str(unclear[0].data.get("reason") or "no reason given"))
        except Exception as error:
            # A name that did not make its own message understood would only mislead every later extraction.
            store().delete("record", entry.id)
            log.error("names: %s learned but %s not reprocessed: %s", entry.refs.get("name"), asked_id,
                      type(error).__name__)
            if attempts >= MAX_ATTEMPTS:
                reason = (str(error) if isinstance(error, _StillUnclear)
                          else f"the reprocess failed ({type(error).__name__})")
                store().put("record", unresolved_id(asked_id), _unresolved(answer, entry, attempts, reason))
            continue
        written.append(entry)
    return written


def _attempts(answer: dict) -> int:
    value = (answer.get("refs") or {}).get(ATTEMPTS) or "0"
    return int(value) if value.isdigit() else 0


def _unresolved(answer: dict, entry: m.RecordEntry, attempts: int, reason: str) -> m.RecordEntry:
    target = {key: value for key, value in entry.refs.items() if key in TARGETS}
    return m.RecordEntry(
        id=unresolved_id(entry.source_event_ids[0]), at=answer.get("at"), kind="info", title=UNRESOLVED_TITLE,
        detail=(f'The message is still not understood after the answer named {_describe(target)} for '
                f'"{entry.refs.get("name")}". It was run again {attempts} times and is not tried again, so the '
                f'name is not kept. Last reason: {reason}.'),
        actor=answer.get("actor"), source_event_ids=entry.source_event_ids,
        refs={"answer": answer["id"], ATTEMPTS: str(attempts)},
    )


def _learned(answer: dict, asked_id: str) -> m.RecordEntry | None:
    refs = answer.get("refs") or {}
    label = refs.get("answer")
    if not isinstance(label, str) or not label.strip() or label == NONE_OF_THESE:
        return None
    if not _permitted(answer):
        return None
    target = _target(label)
    asked = store().get("events", asked_id)
    if target is None or asked is None:
        return None
    name = _normal(_words(m.InboundEvent.model_validate(asked)))
    if not name:
        return None
    sources = [asked_id, *[source for source in answer.get("source_event_ids") or [] if source != asked_id]]
    return m.RecordEntry(
        id=entry_id(asked_id), at=answer.get("at"), kind="info", title=TITLE,
        detail=f'"{name}" means {_describe(target)}.', actor=answer.get("actor"),
        source_event_ids=sources, refs={"name": name, **target},
    )


def _permitted(answer: dict) -> bool:
    """Only the person who was asked, or the superintendent, teaches a name."""
    actor = (answer.get("actor") or "").strip()
    if not actor:
        return False
    item = store().get("waiting", (answer.get("refs") or {}).get("waiting") or "")
    asked = (item or {}).get("on") or ""
    if asked and _normal(actor) == _normal(asked):
        return True
    contact = directory.lookup(actor)
    return contact is not None and "superintendent" in (contact.role or "").lower()


def _target(label: str) -> dict | None:
    """The task, unit or item a clarifying answer named, from the plan and the project only."""
    wanted = _normal(label)
    plan = store().get("plan", "current")
    if not plan:
        return None
    for task in m.Plan.model_validate(plan).tasks:
        if _normal(f"{task.id} {task.name}") == wanted:
            return {"task": task.id}
    for line in m.Plan.model_validate(plan).resources:
        if _normal(line.item) == wanted:
            return {"item": line.item}
    project = store().get("project", "current")
    for unit in (project or {}).get("units") or []:
        if _normal(unit) == wanted:
            return {"unit": unit}
    return None


def _describe(target: dict) -> str:
    key = next(iter(target))
    return f"the {key} {target[key]}"


def _words(event: m.InboundEvent) -> str:
    return (event.transcript or event.text or event.subject or "").strip()


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()
