"""Non-English twins of English extraction cases, through the same extract() the pipeline calls.

    uv run --directory backend python -m app.language.eval.run            replay from mocks/llm (missing answers fail)
    uv run --directory backend python -m app.language.eval.run --live     against the real model, recording answers

A case passes when the specific facts have the twin's types and each expected fact's key data, checked by the same
function as eval/extract. Exit code 0 only when every case passes.
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def _extract_eval():
    spec = importlib.util.spec_from_file_location("extract_eval", ROOT / "eval" / "extract" / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cases() -> list[dict]:
    """The cases, each checked to still expect exactly what its English twin expects."""
    own = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    twins = {c["id"]: c for c in json.loads((ROOT / "eval" / "extract" / "cases.json").read_text(encoding="utf-8"))["cases"]}
    for case in own:
        if twins[case["twin"]]["expect"] != case["expect"]:
            raise ValueError(f"{case['id']} no longer expects what its twin {case['twin']} expects")
    return own


def main(argv: list[str]) -> int:
    from app.core import config

    config.load_dotenv()
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="aurora-language-eval-")
    if "--live" in argv:
        os.environ["USE_MOCK_LLM"] = "false"
        os.environ["LLM_RECORD"] = "true"
    from app.core import llm
    from app.core import models as m
    from app.extract import real

    check = _extract_eval().check
    all_cases = cases()
    passed = 0
    for case in all_cases:
        event = m.InboundEvent.model_validate(case["event"])
        try:
            facts = [f.model_dump() for f in real.extract(event)]
            problems = check(case["expect"], facts)
        except llm.LLMError as error:
            facts, problems = [], [f"model error: {error}"]
        if problems:
            print(f"FAIL {case['id']} ({case['language']}, twin {case['twin']}): " + "; ".join(problems))
            for fact in facts:
                print(f"     {fact['type']} {json.dumps(fact['data'], sort_keys=True)}")
        else:
            passed += 1
            print(f"ok   {case['id']} ({case['language']}, twin {case['twin']})")
    print(f"language twins: {passed}/{len(all_cases)} give the fact types and key data of their English twin")
    return 0 if passed == len(all_cases) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
