"""The fixed path of one event through the areas, and of one decision. Areas decide content; this file decides order."""
import logging
import threading
from datetime import datetime, timezone

from app import activity

from . import models as m
from .llm import LLMError
from .registry import area
from .store import store

RULE_AREAS = ["rules_drawings", "rules_sequence", "rules_resources", "machinereport"]
log = logging.getLogger(__name__)
# The endpoints run in a threadpool and the mailbox loop has its own thread. One lock keeps a decision from
# being overwritten by an ingest that read the flag before it, and two ingests from interleaving their writes.
_lock = threading.RLock()


class DecisionRefused(ValueError):
    """The decisions area refuses an action that does not fit the flag; the decision does not run."""


def reset() -> None:
    """Empty the store and load the project, the plan and the history before the first live event."""
    with _lock, area("guest").mutation_scope():
        s = store()
        s.clear()
        s.put("project", "current", area("record").project())
        s.put("plan", "current", area("schedule").baseline())
        for entry in area("record").baseline():
            s.put("record", entry.id, entry)
        # On the emptied store the machine area answers from its registry file; every area reads this copy.
        for machine in area("machine").machines():
            s.put("machines", machine.id, machine)
        activity.clear()


def ensure_ready() -> None:
    if store().get("project", "current") is None:
        reset()


def _log(entry: m.RecordEntry) -> m.RecordEntry:
    store().put("record", entry.id, entry)
    return entry


def _refresh_proposal(flag: m.Flag) -> None:
    s = store()
    current = s.get("proposals", flag.proposal_id) if flag.proposal_id else None
    if current and (current["basis"] != "calculated" or current["status"] == "accepted"):
        return
    if any(d["flag_id"] == flag.id for d in s.list("decisions")):
        return
    fresh = area("schedule").propose(flag) if flag.status == "open" else None
    if fresh is not None and fresh.basis != "calculated":
        return
    if current and current["status"] == "proposed" and fresh is not None:
        previous = m.Proposal.model_validate(current)
        if previous.model_dump(exclude={"id", "status"}) == fresh.model_dump(exclude={"id", "status"}):
            return
    for raw in s.list("proposals"):
        if raw.get("flag_id") == flag.id and raw["basis"] == "calculated" and raw["status"] == "proposed":
            s.put("proposals", raw["id"], {**raw, "status": "rejected"})
    flag.proposal_id = None
    if fresh is not None:
        # A stale browser must not accept a different plan change under an old proposal id.
        base, version = fresh.id, 2
        while s.get("proposals", fresh.id) is not None:
            fresh.id = f"{base}-{version}"
            version += 1
        s.put("proposals", fresh.id, fresh)
        flag.proposal_id = fresh.id


def accept(event: m.InboundEvent) -> m.IngestResult:
    """Store the event now and let the caller run the areas later, so a channel gets its answer at once.

    The stored row is the duplicate guard from this instant: a redelivery while the work runs is a duplicate.
    A caller that accepts must call run_stored, which keeps ingest's rule that a failure deletes the row again.
    """
    with _lock:
        s = store()
        if s.get("events", event.id) is not None:
            return m.IngestResult(event_id=event.id, duplicate=True)
        s.put("events", event.id, event)
        activity.enqueue(event)
        return m.IngestResult(event_id=event.id)


def run_stored(event_id: str) -> m.IngestResult | None:
    """Run a stored event through every area. Returns None when the row is gone, and re-raises a failure."""
    with _lock:
        s = store()
        if s.get("events", event_id) is None:
            return None
        try:
            return _process(m.InboundEvent.model_validate(s.get("events", event_id)))
        except Exception:
            # Same rule as ingest: a temporary failure must not make the channel's retry a duplicate.
            s.delete("events", event_id)
            raise


def ingest(event: m.InboundEvent) -> m.IngestResult:
    with _lock:
        s = store()
        if s.get("events", event.id) is not None:
            return m.IngestResult(event_id=event.id, duplicate=True)
        try:
            return _process(event)
        except Exception:
            # The event counts as seen only once its areas ran. Keeping it stored would turn every retry into a
            # duplicate, so one temporary failure would silently lose a message the demo needs.
            s.delete("events", event.id)
            raise


def observe(event: m.InboundEvent, facts: list[m.Fact]) -> m.IngestResult:
    """A machine's report: code already made its facts from measured fields, so no model reads the event.

    Everything after extraction runs as for any other event: record, rules, proposals and the outbox.
    """
    with _lock:
        s = store()
        if s.get("events", event.id) is not None:
            return m.IngestResult(event_id=event.id, duplicate=True)
        try:
            return _process(event, observed=facts)
        except Exception:
            s.delete("events", event.id)
            raise


def is_ingested(event_id: str) -> bool:
    """True once the event went through every area. Taking the lock waits out an ingest that may still be undone."""
    with _lock:
        return store().get("events", event_id) is not None


def reprocess(event_id: str) -> m.IngestResult | None:
    """Run a stored event through the areas again, replacing its facts and what they wrote.

    A clarified name can make a message understood that was stored as not understood. The event keeps its own
    received_at, so the rules judge it at the moment it really arrived, not when it was understood. On a failure
    the facts, their record entries and the reason the event was unclear are put back, so the message is never
    left with nothing.
    """
    with _lock:
        s = store()
        raw = s.get("events", event_id)
        if raw is None:
            return None
        event = m.InboundEvent.model_validate(raw)
        replaced = [fact for fact in s.list("facts") if fact.get("event_id") == event_id]
        fact_ids = {fact["id"] for fact in replaced}
        entries = [entry for entry in s.list("record") if (entry.get("refs") or {}).get("fact") in fact_ids]
        for fact in replaced:
            s.delete("facts", fact["id"])
        for entry in entries:
            s.delete("record", entry["id"])
        try:
            return _process(event)
        except Exception:
            for fact in replaced:
                s.put("facts", fact["id"], fact)
            for entry in entries:
                s.put("record", entry["id"], entry)
            raise


def _process(event: m.InboundEvent, observed: list[m.Fact] | None = None) -> m.IngestResult:
    job = activity.Job(event)
    try:
        return _process_steps(event, observed, job)
    except Exception:
        job.fail()
        raise


def _process_steps(event: m.InboundEvent, observed: list[m.Fact] | None, job: activity.Job) -> m.IngestResult:
    s = store()
    previous_records = {row['id'] for row in s.list('record')}
    previous_messages = {row['id'] for row in s.list('outbox')}
    if observed is None:
        job.stage("transcribe")
        event = area("voice").transcribe(event)
        if not any(attachment.kind == "audio" for attachment in event.attachments):
            job.skip("transcribe")
    else:
        job.skip("transcribe")
    s.put("events", event.id, event)

    if observed is not None:
        job.skip("readback")
        job.skip("extract")
        facts: list[m.Fact] = list(observed)
    else:
        # Imported here because the read-back releases a held note through reprocess() of this module.
        from app import voicecheck
        job.stage("readback")
        screened = voicecheck.screen(event)
        if screened is not None:
            check = s.get("voicechecks", event.id)
            job.result(screened, waiting=bool(check and check.get("status") in ("open", "awaiting_text")),
                       screened=True)
            return screened

        # A photo of a title block is read before extraction, so the read is one more fact about the same event.
        job.stage("extract")
        photo_facts: list[m.Fact] = area("titleblock").inspect(event)
        facts = area("extract").extract(event)
        facts.extend(photo_facts)
    for fact in facts:
        s.put("facts", fact.id, fact)

    job.stage("record")
    update: m.RecordUpdate = area("record").apply(event, facts)
    logged = [_log(entry) for entry in update.entries]
    for item in update.waiting_open:
        s.put("waiting", item.id, item)
    for item_id in update.waiting_close:
        current = s.get("waiting", item_id)
        if current:
            s.put("waiting", item_id, {**current, "status": "done"})

    job.stage("drawings")
    diffs: list[m.DrawingDiff] = area("drawings").diffs_for(event, facts)
    crosscheck = area("crosscheck")
    for diff in diffs:
        s.put("diffs", diff.id, diff)
        crosscheck.on_diff(diff, event)

    job.stage("rules")
    flags: list[m.Flag] = []
    for name in RULE_AREAS:
        flags.extend(area(name).evaluate(event, facts))
    for flag in flags:
        flag.evidence = area("guest").public_sources(flag.evidence)
        is_new = s.get("flags", flag.id) is None
        proposal = area("schedule").propose(flag) if is_new and flag.status == "open" else None
        if proposal is not None:
            s.put("proposals", proposal.id, proposal)
            flag.proposal_id = proposal.id
        if not is_new:
            _refresh_proposal(flag)
        s.put("flags", flag.id, flag)
        if is_new:
            logged.append(_log(m.RecordEntry(
                id=f"r-flag-{flag.id}", at=flag.raised_at, kind="flag", title=flag.title, detail=flag.summary,
                actor="Aurora", source_event_ids=[e.event_id for e in flag.evidence], refs={"flag": flag.id},
            )))

    # An automatic hold is a decision in the middle of the ingest; the response must show the flag it held.
    try:
        area("autonomy").on_flags(flags)
    except Exception as error:
        # A failing autonomy area must never turn the whole ingest into an error.
        log.error("pipeline: autonomy on_flags failed: %s", type(error).__name__)
    stored = {raw["id"]: raw for raw in s.list("flags")}
    flags = [m.Flag.model_validate(stored[flag.id]) for flag in flags]

    job.stage("answer")
    answer: m.Answer | None = area("qa").answer(event, facts)
    if answer is not None:
        answer.sources = area("guest").public_sources(answer.sources)
        s.put("answers", answer.id, answer)
        logged.append(_log(m.RecordEntry(
            id=f"r-ans-{answer.id}", at=answer.created_at, kind="answer", title=f"Answered: {answer.question}",
            detail=answer.text, actor="Aurora", source_event_ids=[event.id], refs={"answer": answer.id},
        )))

    job.stage("delivery")
    with area("guest").delivery_scope([event.id]):
        outbox: list[m.OutboundMessage] = area("outbox").react(event, facts, flags, answer)
        # The title block answer is sent after the usual notices: it answers the sender, in its own thread.
        outbox.extend(area("titleblock").react(event, facts))
    for message in outbox:
        s.put("outbox", message.id, message)
        delivery_label = {"sent": "Sent to", "simulated": "Simulated message to",
                          "queued": "Queued for", "failed": "Delivery failed to"}[message.status]
        logged.append(_log(m.RecordEntry(
            id=f"r-out-{message.id}", at=message.created_at, kind="notice", title=f"{delivery_label} {message.to}",
            detail=message.text, actor="Aurora", source_event_ids=[event.id], refs={"message": message.id},
        )))

    # Cross-sheet and rework hooks persist their own rows. Return their new output once, without old history.
    returned_records = {entry.id for entry in logged}
    logged.extend(m.RecordEntry.model_validate(row) for row in s.list('record')
                  if row['id'] not in previous_records and row['id'] not in returned_records)
    returned_messages = {message.id for message in outbox}
    outbox.extend(m.OutboundMessage.model_validate(row) for row in s.list('outbox')
                  if row['id'] not in previous_messages and row['id'] not in returned_messages)
    result = m.IngestResult(
        event_id=event.id, facts=facts, record=logged, flags=flags, diffs=diffs, outbox=outbox, answer=answer
    )
    job.result(result)
    return result


def command(text: str) -> m.CommandResponse:
    """A typed instruction becomes a proposal, stored under the same lock as a decision.

    The command reads the flag and the plan before it stores, so without the lock a decision taken meanwhile
    would leave a proposal behind that was built from state the superintendent already changed.
    """
    with _lock:
        response: m.CommandResponse = area("command").interpret(text)
        if response.proposal is not None:
            store().put("proposals", response.proposal.id, response.proposal)
        return response


class MissingModelAnswer(RuntimeError):
    """A prepared message cannot be read because the model is mocked and its answer was never recorded."""


def play_next() -> m.IngestResult | None:
    """Ingest the next event of the prepared scenario that nobody has seen, under the lock.

    Reading the seen set and ingesting in one locked step is what stops two clicks on Play next event from
    picking the same event. A missing recorded answer stops the walk with a sentence naming the message, so the
    history is never walked past a message Aurora could not read.
    """
    with _lock:
        seen = {event["id"] for event in store().list("events")}
        for event in area("replay").events():
            if event.id not in seen:
                try:
                    return ingest(event)
                except LLMError as error:
                    text = " ".join(event.text.split())
                    if len(text) > 160:
                        text = text[:157] + "..."
                    raise MissingModelAnswer(
                        f"{event.id} from {event.sender} on {event.channel} cannot be played: {error}. "
                        f"Its message is: {text!r}"
                    ) from None
        return None


def decide(request: m.DecisionRequest) -> m.Decision:
    """The only path by which an action with consequences runs: a human decision on a flag."""
    with _lock:
        s = store()
        flag = s.get("flags", request.flag_id)
        if flag is None:
            raise KeyError(request.flag_id)
        with area("guest").delivery_scope([item["event_id"] for item in flag.get("evidence", [])]):
            decision: m.Decision = area("decisions").decide(request)
        s.put("decisions", decision.id, decision)
        area("learning").on_decision(decision)
        refs = {"flag": decision.flag_id}
        if decision.authorization_id:
            refs["authorization"] = decision.authorization_id
        _log(m.RecordEntry(
            id=f"r-dec-{decision.id}", at=decision.decided_at, kind="decision",
            title=f"{decision.decided_by} decided: {decision.action.replace('_', ' ')}",
            detail=decision.reason or flag["title"], actor=decision.decided_by, refs=refs,
        ))
        if decision.action == "release_work":
            _revoke_automatic_hold(s, decision)
        return decision


def _revoke_automatic_hold(s, decision: m.Decision) -> None:
    """A person releasing work Aurora held under a grant has overruled the grant, so it stops applying."""
    holds = [raw for raw in s.list("decisions")
             if raw.get("flag_id") == decision.flag_id and raw.get("authorization_id")]
    if not holds:
        return
    try:
        area("autonomy").revoke(holds[-1]["authorization_id"], decision.decided_by)
    except (KeyError, ValueError) as error:
        log.error("pipeline: release did not revoke authorization: %s", type(error).__name__)


def now() -> datetime:
    return datetime.now(timezone.utc)
