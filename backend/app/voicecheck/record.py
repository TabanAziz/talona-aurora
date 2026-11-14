"""One deliberate real-model run: the noisy e53 voice note is read back, corrected by its sender, and used.

    uv run --directory backend python -m app.voicecheck.record

At heavy site noise the speech service heard "3D" where Hannah Kowalski said "3B" (both transcripts were measured
with the real service). The note is held, Hannah presses Correct it and types what she said, and only that text
goes through extraction, with the real model. Every model answer is recorded under mocks/llm, so the test replays
the same run offline. Exit code 0 only when the record has a fact for 3B and none for 3D.
"""
import json
import os
import sys
from datetime import timedelta

from app.core import config

HEARD = "On the next working day, we start rough electrical in 3D. The wire is cut to length from E-201 Rev A."
SAID = "On the next working day, we start rough electrical in 3B. The wire is cut to length from E201 Rev A."


def e53_heard():
    """The e53 voice note as the speech service transcribed the noisy clip."""
    from app.core import models as m

    raw = next(item for item in json.loads(
        (config.ROOT / "data" / "messages" / "events.json").read_text(encoding="utf-8")) if item["id"] == "e53")
    return m.InboundEvent.model_validate({**raw, "transcript": HEARD})


def answer(event_id: str, after, text: str, subject: str | None = None):
    """A Telegram message or button press from Hannah, `after` the note."""
    from app.core import models as m

    note = e53_heard()
    at = note.received_at + after
    return m.InboundEvent(id=event_id, channel="telegram", sent_at=at, received_at=at, sender=note.sender,
                          sender_role=note.sender_role, thread=note.thread, subject=subject, text=text)


def run() -> list[dict]:
    """Hold the heard note, press Correct it, type the said text. Returns the facts stored for e53."""
    from app import voicecheck
    from app.core import pipeline
    from app.core.store import store

    held = pipeline.ingest(e53_heard())
    [read_back] = held.outbox
    pipeline.ingest(answer("e53-correct", timedelta(minutes=1), voicecheck.CORRECT, subject=read_back.text))
    pipeline.ingest(answer("e53-text", timedelta(minutes=2), SAID))
    return [fact for fact in store().list("facts") if fact["event_id"] == "e53"]


def units(facts: list[dict]) -> set[str]:
    return {str(fact["data"].get("unit")) for fact in facts if fact["data"].get("unit")}


def main() -> int:
    from app.core import pipeline

    config.load_dotenv()
    if not os.environ.get("MISTRAL_API_KEY"):
        sys.exit("record: MISTRAL_API_KEY is not set")
    os.environ["USE_MOCK_LLM"] = "false"
    os.environ["LLM_RECORD"] = "true"
    # Forced, not defaulted: a live flag in .env must never let this run send a message or call the speech service.
    for name in config.EXTERNAL:
        if name != "llm":
            os.environ[f"USE_MOCK_{name.upper()}"] = "true"
    for name in config.AREAS:
        os.environ.pop(f"USE_MOCK_{name.upper()}", None)
    scratch = config.ROOT / ".local" / "voicecheck-record"
    scratch.mkdir(parents=True, exist_ok=True)
    for child in scratch.glob("*"):
        if child.is_file():
            child.unlink()
    os.environ["DATA_DIR"] = str(scratch)

    pipeline.reset()
    facts = run()
    print(f"heard: {HEARD}")
    print(f"said:  {SAID}")
    print(f"e53 facts after the correction: {[(fact['type'], fact['data']) for fact in facts]}")
    found = units(facts)
    ok = "3B" in found and "3D" not in found
    print("PASS: a fact for 3B and none for 3D" if ok else f"FAIL: units {sorted(found)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
