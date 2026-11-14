"""Fixed crew replies to the A-201 Rev B to Rev C change, judged against their expected verdicts.

    uv run --directory backend python -m app.readback.eval           replay from mocks/llm (missing answers fail)
    uv run --directory backend python -m app.readback.eval --live    against the real model

Exit code 0 only when every reply gets its expected verdict.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(argv: list[str]) -> int:
    from app.core import config

    config.load_dotenv()
    if "--live" in argv:
        os.environ["USE_MOCK_LLM"] = "false"
    from app.core import models as m
    from app.core import scenario

    from .judge import judge

    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    diff = next(
        m.DrawingDiff.model_validate(d)
        for step in scenario.load()["by_event"].values() for d in step.get("diffs", []) if d["id"] == cases["diff"]
    )
    passed = 0
    for case in cases["cases"]:
        result = judge(diff, case["reply"])
        ok = result.verdict == case["verdict"]
        passed += ok
        print(f"{'ok  ' if ok else 'FAIL'} {case['id']}: {result.verdict} (expected {case['verdict']}), said {result.said}")
    print(f"readback fixed replies: {passed}/{len(cases['cases'])} passed")
    return 0 if passed == len(cases["cases"]) else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
