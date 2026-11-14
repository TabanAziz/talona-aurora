"""Fixed instruction cases through the production command interpreter; --live calls the provider."""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))


def main():
    from app.core import config, pipeline, scenario
    from app.core import store as storage
    from app.command import real

    config.load_dotenv()
    for name in config.AREAS:
        os.environ[f"USE_MOCK_{name.upper()}"] = "true"
    for name in config.EXTERNAL:
        os.environ[f"USE_MOCK_{name.upper()}"] = "true"
    live = "--live" in sys.argv
    os.environ["USE_MOCK_LLM"] = "false" if live else "true"
    os.environ["LLM_RECORD"] = "true" if "--record" in sys.argv else "false"
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    passed, results = 0, []
    with tempfile.TemporaryDirectory(prefix="aurora-command-eval-") as directory:
        os.environ["DATA_DIR"] = directory
        storage._store = None
        for case in cases:
            pipeline.reset()
            s = storage.store()
            stale = copy.deepcopy(scenario.load()["by_event"]["e02"]["flags"]["rules_drawings"][0])
            if case.get("held"):
                stale["status"] = "held"
            s.put("flags", stale["id"], stale)
            target = case.get("flag")
            if case.get("resource"):
                resource = copy.deepcopy(scenario.load()["by_event"]["e04"]["flags"]["rules_resources"][0])
                s.put("flags", resource["id"], resource)
                target = resource["id"]
            before = {name: s.list(name) for name in ("plan", "flags", "decisions", "outbox")}
            response = real.interpret(case["text"])
            proposal = response.proposal
            actual = proposal.action if proposal else None
            ok = (actual == case["expect"] and bool(response.message.strip())
                  and (not proposal or proposal.flag_id == target)
                  and before == {name: s.list(name) for name in before})
            if case["expect"] is None and "unavailable" in response.message.lower():
                ok = False
            passed += int(ok)
            results.append({"id": case["id"], "passed": ok, "response": response.model_dump(mode="json")})
            print(f"{'ok' if ok else 'FAIL'} {case['id']}: {actual or 'explained refusal'}", flush=True)
        storage._store._db.close()
        storage._store = None
    evidence = config.ROOT / "evidence" / "command"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / ("live.json" if live else "replay.json")).write_text(
        json.dumps({"mode": "live" if live else "recorded", "passed": passed, "total": len(cases), "results": results}, indent=2) + "\n",
        encoding="utf-8")
    print(f"command {'live' if live else 'recorded'} cases: {passed}/{len(cases)} passed; no plan, flag, decision or outbound mutation")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
