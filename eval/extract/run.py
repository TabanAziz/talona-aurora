"""Golden cases for fact extraction, through the same extract() the pipeline calls.

    uv run --directory backend python ../eval/extract/run.py --live     against the real model
    uv run --directory backend python ../eval/extract/run.py            replay from mocks/llm (missing answers fail)

A case passes when the specific facts (every type except other) have exactly the expected types, and each
expected fact's data keys match one returned fact of that type. Exit code 0 only when every case passes.
"""
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))


def _same(expected: object, actual: object) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()
    if isinstance(expected, list) and isinstance(actual, list):
        return sorted(_same_key(v) for v in expected) == sorted(_same_key(v) for v in actual)
    return expected == actual


def _same_key(value: object) -> str:
    return value.strip().lower() if isinstance(value, str) else json.dumps(value)


def check(expect: list[dict], facts: list[dict]) -> list[str]:
    specific = [f for f in facts if f["type"] != "other"]
    problems = []
    want, got = Counter(e["type"] for e in expect), Counter(f["type"] for f in specific)
    if want != got:
        problems.append(f"types {dict(got) or 'none'}, expected {dict(want) or 'none'}")
    for e in expect:
        candidates = [f for f in specific if f["type"] == e["type"]]
        if not any(all(_same(v, f["data"].get(k)) for k, v in e["data"].items()) for f in candidates):
            shown = [f["data"] for f in candidates]
            problems.append(f"{e['type']}: expected {e['data']}, got {shown}")
    return problems


def main(argv: list[str]) -> int:
    from app.core import config

    config.load_dotenv()
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="aurora-eval-")
    if "--live" in argv:
        os.environ["USE_MOCK_LLM"] = "false"
    from app.core import llm
    from app.core import models as m
    from app.extract import real
    from app.extract.record import scenario_events

    scenario = {e.id: e for e in scenario_events()}
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    passed = 0
    for case in cases:
        if "scenario_event" in case:
            event = scenario[case["scenario_event"]]
        else:
            event = m.InboundEvent.model_validate({"received_at": case["event"]["sent_at"], **case["event"]})
        try:
            facts = [f.model_dump() for f in real.extract(event)]
            problems = check(case["expect"], facts)
        except llm.LLMError as error:
            facts, problems = [], [f"model error: {error}"]
        if problems:
            print(f"FAIL {case['id']}: " + "; ".join(problems))
            for fact in facts:
                print(f"     {fact['type']} {json.dumps(fact['data'], sort_keys=True)}")
        else:
            passed += 1
            print(f"ok   {case['id']}")
    print(f"extract golden cases: {passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
