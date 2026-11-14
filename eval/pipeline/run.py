"""End-to-end detection evaluation: fixed cases through the same pipeline the app runs.

    uv run --directory backend python ../eval/pipeline/run.py --live --record    real model, saves replay files
    uv run --directory backend python ../eval/pipeline/run.py --live             real model, no files written
    uv run --directory backend python ../eval/pipeline/run.py                    replay from mocks/llm (fast, offline)
    options: --only <case id> (repeatable)   --out <folder for report.md and report.json>

Each case resets the store to the project baseline, ingests its events in order with pipeline.ingest and
compares the flags that exist afterwards with the expected ones in cases.json. External services stay mocked;
only the language model is real with --live. Exit code 0 only when every case passes.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))


def _norm(value: object) -> str:
    return str(value).strip().lower()


def matches(expected: dict, flag: dict) -> bool:
    if flag["type"] != expected["type"]:
        return False
    affected = flag.get("affected") or {}
    return all(_norm(affected.get(key)) == _norm(value) for key, value in expected.get("affected", {}).items())


def build_events(case: dict, library: dict):
    from app.core import models as m

    events = []
    for entry in case["events"]:
        body = dict(library[entry["msg"]])
        sent = datetime.fromisoformat(entry["sent_at"].replace("Z", "+00:00"))
        delay = 0 if body["channel"] == "schedule" else 3
        events.append(m.InboundEvent.model_validate({
            **body, "id": entry["id"], "sent_at": sent, "received_at": sent + timedelta(seconds=delay),
        }))
    return events


def run_case(case: dict, library: dict) -> dict:
    from app.core import pipeline
    from app.core.store import store

    pipeline.reset()
    events = build_events(case, library)
    first_seen: dict[str, str] = {}
    first_evidence: dict[str, list[str]] = {}
    errors: list[str] = []
    for event in events:
        try:
            result = pipeline.ingest(event)
        except Exception as error:  # a model or code failure is a result of the case, not a crash of the run
            errors.append(f"{event.id}: {type(error).__name__}: {error}")
            continue
        for flag in result.flags:
            if flag.id not in first_seen:
                first_seen[flag.id] = event.id
                first_evidence[flag.id] = [e.event_id for e in flag.evidence]
    found = store().list("flags")
    received = {e.id: e.received_at for e in events}

    remaining = list(found)
    hits, missed = [], []
    for expected in case["expect_flags"]:
        match = next((f for f in remaining if matches(expected, f)), None)
        if match is None:
            missed.append(expected)
            continue
        remaining.remove(match)
        raised_at = datetime.fromisoformat(match["raised_at"].replace("Z", "+00:00"))
        evidence_ids = [e["event_id"] for e in match.get("evidence", [])]
        evidence_ok = bool(evidence_ids) and all(i in received and match["evidence"][n]["quote"]
                                                  for n, i in enumerate(evidence_ids))
        # judged on the evidence the flag had when it first appeared, later confirmations are added on purpose
        initial = first_evidence.get(match["id"], [])
        latest_info = max((received[i] for i in initial if i in received), default=None)
        work_start = match.get("work_starts_at")
        hits.append({
            "flag_id": match["id"],
            "type": match["type"],
            "raised_by": first_seen.get(match["id"]),
            "on_expected_event": first_seen.get(match["id"]) == expected["raised_by"],
            "not_before_information": latest_info is not None and raised_at >= latest_info,
            "before_work_start": None if not work_start else
            raised_at < datetime.fromisoformat(work_start.replace("Z", "+00:00")),
            "evidence_ok": evidence_ok,
            "status_ok": None if "final_status" not in expected else match["status"] == expected["final_status"],
        })
    return {
        "id": case["id"],
        "note": case.get("note", ""),
        "expected": len(case["expect_flags"]),
        "hits": hits,
        "missed": missed,
        "false_alarms": [{"id": f["id"], "type": f["type"], "title": f["title"]} for f in remaining],
        "errors": errors,
        "passed": not missed and not remaining and not errors and all(
            h["on_expected_event"] and h["not_before_information"] and h["before_work_start"] is not False
            and h["evidence_ok"] and h["status_ok"] is not False for h in hits
        ),
    }


def summarize(results: list[dict], cases: list[dict]) -> dict:
    hits = [h for r in results for h in r["hits"]]
    with_work = [h for h in hits if h["before_work_start"] is not None]
    with_status = [h for h in hits if h["status_ok"] is not None]
    no_problem = {c["id"] for c in cases if not c["expect_flags"]}
    return {
        "cases": len(results),
        "cases_with_problem": len(results) - len(no_problem),
        "cases_without_problem": len(no_problem),
        "cases_passed": sum(r["passed"] for r in results),
        "cases_with_errors": sum(bool(r["errors"]) for r in results),
        "expected_flags": sum(r["expected"] for r in results),
        "flags_found": len(hits),
        "missed_problems": sum(len(r["missed"]) for r in results),
        "false_alarms": sum(len(r["false_alarms"]) for r in results),
        "no_problem_cases_with_a_flag": sum(1 for r in results if r["id"] in no_problem and r["false_alarms"]),
        "timing_on_expected_event": f"{sum(h['on_expected_event'] for h in hits)}/{len(hits)}",
        "timing_not_before_information": f"{sum(h['not_before_information'] for h in hits)}/{len(hits)}",
        "timing_before_work_start": f"{sum(bool(h['before_work_start']) for h in with_work)}/{len(with_work)}",
        "evidence_cites_arrived_events": f"{sum(h['evidence_ok'] for h in hits)}/{len(hits)}",
        "final_status_as_expected": f"{sum(bool(h['status_ok']) for h in with_status)}/{len(with_status)}",
    }


def _commit() -> str:
    """The commit the numbers are measured on, so a reader can tell how old they are."""
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True, timeout=10)
        return done.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def render(summary: dict, results: list[dict], meta: dict) -> str:
    lines = [
        "# Detection evaluation",
        "",
        f"Run at {meta['when']} UTC, mode: {meta['mode']}, model: {meta['model']}, measured on commit "
        f"{meta.get('commit', 'unknown')}.",
        f"Areas with a real module: {', '.join(meta['real_areas'])}. Areas still on their mock: "
        f"{', '.join(meta['mock_areas']) or 'none'}.",
        "",
        "Every case starts from the project baseline, ingests its events through `pipeline.ingest` and compares "
        "the flags that exist afterwards with the expected ones. A flag that matches no expected one is a false "
        "alarm; an expected flag nobody raised is a missed problem. The expected answers are in "
        "`eval/pipeline/cases.json` and nowhere else.",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Cases | {summary['cases']} ({summary['cases_with_problem']} with a problem, "
        f"{summary['cases_without_problem']} without) |",
        f"| Cases passed | {summary['cases_passed']}/{summary['cases']} |",
        f"| Cases with an error (model or code) | {summary['cases_with_errors']} |",
        f"| Flags expected | {summary['expected_flags']} |",
        f"| Flags found (matching an expected one) | {summary['flags_found']} |",
        f"| Missed problems | {summary['missed_problems']} |",
        f"| False alarms | {summary['false_alarms']} (in {summary['no_problem_cases_with_a_flag']} of "
        f"{summary['cases_without_problem']} cases without a problem) |",
        f"| Flag raised by the event that completed the evidence | {summary['timing_on_expected_event']} |",
        f"| Flag not raised before its evidence had arrived | {summary['timing_not_before_information']} |",
        f"| Flag raised before the work starts | {summary['timing_before_work_start']} |",
        f"| Evidence cites events that arrived | {summary['evidence_cites_arrived_events']} |",
        f"| Final status as expected (where stated) | {summary['final_status_as_expected']} |",
        "",
        "## Cases",
        "",
    ]
    for r in results:
        lines.append(f"- {'ok  ' if r['passed'] else 'FAIL'} `{r['id']}`: {r['note']}")
        for item in r["missed"]:
            lines.append(f"  - missed: {item['type']} {item.get('affected', {})}")
        for item in r["false_alarms"]:
            lines.append(f"  - false alarm: {item['type']} {item['id']}: {item['title']}")
        for hit in r["hits"]:
            problems = [k for k in ("on_expected_event", "not_before_information", "evidence_ok") if not hit[k]]
            if hit["before_work_start"] is False:
                problems.append("before_work_start")
            if hit["status_ok"] is False:
                problems.append("status")
            if problems:
                lines.append(f"  - {hit['flag_id']}: failed {', '.join(problems)}")
        for error in r["errors"]:
            lines.append(f"  - error: {error}")
    lines += [
        "",
        "## What this does not test",
        "",
        f"- Sample size is {summary['cases']} synthetic cases written by the team, so the numbers show that the "
        "known paths work, not a rate on real site traffic.",
        "- Voice notes arrive as text here: speech to text is not part of this run.",
        "- Questions from crews and the wording of answers are not scored, only the flags.",
        "- Delivery to the real Telegram and email services is not tested: the channel modules run, and both "
        "send through their mocked service, so the formats are covered and the network is not.",
        "- One run per case at temperature 0; run-to-run variation of the model is not measured.",
        "A repeated live run on the same commit missed the truck delivery case (p10-too-few-trucks) that this run passed, so the model is not perfectly repeatable and this is one measured result, not a guarantee. The committed recordings replay this run's answers.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    from app.core import config

    config.load_dotenv()
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="aurora-eval-")
    for name in config.EXTERNAL:
        os.environ.setdefault(f"USE_MOCK_{name.upper()}", "true")
    live = "--live" in argv
    if live:
        os.environ["USE_MOCK_LLM"] = "false"
    if "--record" in argv:
        os.environ["LLM_RECORD"] = "true"

    only = [argv[i + 1] for i, a in enumerate(argv) if a == "--only"]
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else HERE
    data = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if not only or c["id"] in only]

    from app.core import registry

    results = []
    for case in cases:
        result = run_case(case, data["messages"])
        results.append(result)
        print(f"{'ok  ' if result['passed'] else 'FAIL'} {case['id']}")
        for line in (f"     missed {m['type']} {m.get('affected')}" for m in result["missed"]):
            print(line)
        for item in result["false_alarms"]:
            print(f"     false alarm {item['type']} {item['id']}: {item['title']}")
        for error in result["errors"]:
            print(f"     error {error}")

    summary = summarize(results, cases)
    real = [a for a in config.AREAS if not registry.is_mock(a)]
    meta = {
        "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "mode": "real model" if live else "replay of recorded model answers",
        "model": os.environ.get("LLM_MODEL") or "not set",
        "commit": _commit(),
        "real_areas": real,
        "mock_areas": [a for a in config.AREAS if a not in real],
    }
    if not only and (live or "--out" in argv):
        (out / "report.md").write_text(render(summary, results, meta), encoding="utf-8", newline="\n")
        (out / "report.json").write_text(json.dumps({"meta": meta, "summary": summary, "cases": results},
                                                    indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["cases_passed"] == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
