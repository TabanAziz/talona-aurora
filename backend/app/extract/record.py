"""Run the real extractor over the scenario events and print the facts.

    uv run --directory backend python -m app.extract.record            replay from mocks/llm
    uv run --directory backend python -m app.extract.record --live     call the model and record replay files

Arguments after the flags pick event ids (default: all scenario events).
"""
import os
import sys
import tempfile

from app.core import config, scenario
from app.core import models as m


def scenario_events() -> list[m.InboundEvent]:
    """The scenario events as extraction sees them: voice notes carry the scenario's transcript."""
    events = []
    for raw in scenario.load()["events"]:
        event = m.InboundEvent.model_validate(raw)
        transcript = scenario.for_event(event.id).get("transcript")
        if transcript and not event.transcript:
            event = event.model_copy(update={"transcript": transcript})
        events.append(event)
    return events


def main(argv: list[str]) -> int:
    live = "--live" in argv
    wanted = [a for a in argv if not a.startswith("--")]
    config.load_dotenv()
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="aurora-extract-")
    if live:
        os.environ["USE_MOCK_LLM"] = "false"
        os.environ["LLM_RECORD"] = "true"
    from app.extract import real

    for event in scenario_events():
        if wanted and event.id not in wanted:
            continue
        for fact in real.extract(event):
            print(fact.model_dump_json())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
