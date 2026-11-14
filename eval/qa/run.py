"""Fixed crew questions through the full pipeline, in scenario order.

    uv run --directory backend python ../eval/qa/run.py --live     against the real model
    uv run --directory backend python ../eval/qa/run.py            replay from mocks/llm (missing answers fail)

A question passes when its answer meets every expectation of its case: text prefix, one of several words,
basis, escalation and the source events it must cite. Exit code 0 only when every question passes.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))


def check(expect: dict, answer: dict | None) -> list[str]:
    if answer is None:
        return ["no answer"]
    problems = []
    text = answer["text"]
    if "prefix" in expect and not text.startswith(expect["prefix"]):
        problems.append(f"text does not start with {expect['prefix']!r}")
    if "contains_any" in expect and not any(w.lower() in text.lower() for w in expect["contains_any"]):
        problems.append(f"text names none of {expect['contains_any']}")
    if "basis" in expect and answer["basis"] != expect["basis"]:
        problems.append(f"basis {answer['basis']}, expected {expect['basis']}")
    if "escalated" in expect and answer["escalated"] != expect["escalated"]:
        problems.append(f"escalated {answer['escalated']}, expected {expect['escalated']}")
    cited = {s["event_id"] for s in answer["sources"]}
    missing = [e for e in expect.get("sources_include", []) if e not in cited]
    if missing:
        problems.append(f"sources {sorted(cited) or 'none'} miss {missing}")
    return problems


def main(argv: list[str]) -> int:
    from app.core import config

    config.load_dotenv()
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="aurora-eval-qa-")
    if "--live" in argv:
        os.environ["USE_MOCK_LLM"] = "false"
    from app.core import llm, pipeline, scenario
    from app.core import models as m

    events = {e["id"]: e for e in scenario.load()["events"]}
    steps = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["steps"]
    pipeline.reset()
    asked = passed = 0
    for step in steps:
        if "ingest" in step:
            pipeline.ingest(m.InboundEvent.model_validate(events[step["ingest"]]))
            continue
        if "decide" in step:
            pipeline.decide(m.DecisionRequest.model_validate(step["decide"]))
            continue
        asked += 1
        raw = events[step["scenario_event"]] if "scenario_event" in step else {"received_at": step["event"]["sent_at"], **step["event"]}
        try:
            result = pipeline.ingest(m.InboundEvent.model_validate(raw))
            answer = result.answer.model_dump(mode="json") if result.answer else None
            problems = check(step["expect"], answer)
        except llm.LLMError as error:
            answer, problems = None, [f"model error: {error}"]
        if problems:
            print(f"FAIL {step['id']}: " + "; ".join(problems))
            if answer:
                print(f"     {answer['basis']} escalated={answer['escalated']} {answer['text']}")
        else:
            passed += 1
            print(f"ok   {step['id']}: {answer['text']}")
    print(f"qa fixed questions: {passed}/{asked} passed")
    return 0 if passed == asked else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
