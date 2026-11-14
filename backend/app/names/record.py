"""One deliberate real-model run: a corridor message is clarified, its name is learned, and it is understood.

    uv run --directory backend python -m app.names.record

The plan has framing work on the day, so the e18 voice-note transcript is shifted to it (the message only says
"today"). The unclear fact is the one the extraction stores for a message that names work the project lists do not
know, and the question and the answer go through the real `app.clarify` code. Then `names.learn()` learns the name
and runs the message through the pipeline again with the real model, which now sees the known name in its prompt.
Every model answer is recorded under mocks/llm, so the run repeats offline. Exit code 0 only when the reprocessed
message states work with the learned task.
"""
import json
import os
import sys
from datetime import datetime, timedelta

from app.core import config

UNCLEAR = "answer invalid after one repair: fact 1: type work_started needs unit or task"


def main() -> int:
    from app import clarify
    from app.core import models as m
    from app.core import pipeline
    from app.core.store import store
    from app.names import real as names

    config.load_dotenv()
    if not os.environ.get("MISTRAL_API_KEY"):
        sys.exit("record: MISTRAL_API_KEY is not set")
    os.environ["USE_MOCK_LLM"] = "false"
    os.environ["LLM_RECORD"] = "true"
    for name in config.EXTERNAL:
        os.environ.setdefault(f"USE_MOCK_{name.upper()}", "true")
    scratch = config.ROOT / ".local" / "names-record"
    scratch.mkdir(parents=True, exist_ok=True)
    for child in scratch.glob("*"):
        child.unlink()
    os.environ["DATA_DIR"] = str(scratch)

    pipeline.reset()
    plan = m.Plan.model_validate(store().get("plan", "current"))
    framing = sorted((task for task in plan.tasks if task.crew == "Framing crew"), key=lambda task: task.start)
    if not framing:
        sys.exit("record: the plan has no framing work to name")
    sent = framing[0].start.replace(hour=6, minute=50)
    raw = next(item for item in json.loads(
        (config.ROOT / "data" / "messages" / "events.json").read_text(encoding="utf-8")) if item["id"] == "e18")
    transcripts = json.loads((config.ROOT / "data" / "messages" / "voice_texts.json").read_text(encoding="utf-8"))
    event = m.InboundEvent.model_validate({
        **raw, "sent_at": sent, "received_at": sent + timedelta(seconds=2),
        "transcript": transcripts["e18"]["text"],
    })
    store().put("events", event.id, event)
    unclear = m.Fact(id="f-e18-unclear", event_id=event.id, type="other", subject="Not understood",
                     data={"not_understood": True, "reason": UNCLEAR, "note": "work started"},
                     confidence=0.2, quote=event.transcript)
    store().put("facts", unclear.id, unclear)
    print(f"e18: {event.transcript}")

    [question] = [message for message in clarify.react(event, [unclear]) if message.id.startswith("o-clarify-")]
    store().put("outbox", question.id, question.model_copy(update={"status": "simulated"}))
    print(f"question: {question.text}")
    labels = [label for label in question.buttons if label != clarify.NONE_OF_THESE]
    chosen = next((label for label in labels if "corridor" in label.lower()), labels[0])
    reply = m.InboundEvent(id="e18-reply", channel="telegram", sent_at=sent + timedelta(minutes=5),
                           received_at=sent + timedelta(minutes=5), sender="Marco Ruiz", text=chosen)
    store().put("events", reply.id, reply)
    if not clarify._answered(reply):
        sys.exit("record: the answer did not close the question")
    answer = store().get("record", clarify.answer_entry_id(event.id))
    print(f"answer: {answer['refs']['answer']} by {answer['actor']}")

    learned = names.learn()
    print(f"learned: {[entry.refs for entry in learned]}")
    facts = [fact for fact in store().list("facts") if fact["event_id"] == event.id]
    flags = [flag for flag in store().list("flags")
             if event.id in [evidence["event_id"] for evidence in flag.get("evidence") or []]]
    print(f"e18 after the reprocess: {[(fact['type'], fact['data'].get('task') or fact['data'].get('unit')) for fact in facts]}")
    print(f"flags from e18: {[(flag['type'], flag['title']) for flag in flags]}")
    understood = any(fact["type"] in ("work_planned", "work_started") and fact["data"].get("task") for fact in facts)
    print("PASS: the corridor message is understood with the learned task" if understood
          else "FAIL: the corridor message is still not understood")
    return 0 if understood else 1


if __name__ == "__main__":
    sys.exit(main())
