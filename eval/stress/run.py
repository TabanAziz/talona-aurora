"""Run the fixed detection cases in clean wording and in five messy styles, and report where detection breaks.

    uv run --directory backend python ../eval/stress/run.py --live --record   real model for the variants, records
    uv run --directory backend python ../eval/stress/run.py --live             real model, no files written
    uv run --directory backend python ../eval/stress/run.py --offline          replay of the committed recordings

The clean baseline is read from the committed replay files of `eval/pipeline`, so this run never rewrites them.
Only the variants call the real model. The expected flags come from `eval/pipeline/cases.json`; they are only
compared with, never put into a prompt. Writes report.md and report.json next to this file.
"""
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

STYLES = ("site_slang", "typos", "mixed_language", "asr", "long")
KINDS = ("clean",) + STYLES
# A repair for an answer that failed validation is the other model call an ingest can make.
REPAIR_MARGIN = 0.25
LIMITATIONS = [
    "The variants are written by the same model that reads them, so they share its habits; real site messages "
    "would be harder in other ways.",
    "The variants keep the unit, sheet, revision, count and day of the original by construction; a real message "
    "that loses one of those is a different case, not covered here.",
    "Voice notes, speech to text, channels and answers are not part of this run.",
    "One run per case at temperature 0; run-to-run variation is not measured.",
]


def _scratch() -> Path:
    """A scratch DATA_DIR under the gitignored .local, so no run leaves files in the repo."""
    path = ROOT / ".local" / "stress-run"
    if path.exists():
        for child in path.iterdir():
            child.unlink()
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_pipeline_eval():
    spec = importlib.util.spec_from_file_location("pipeline_eval", ROOT / "eval" / "pipeline" / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case_library(library: dict, variants: dict, style: str | None) -> tuple[dict, list[str]]:
    """The message library with each text in the given style, and the messages that have no variant."""
    if style is None:
        return library, []
    out, missing = {}, []
    for message_id, message in library.items():
        text = ((variants.get("messages") or {}).get(message_id) or {}).get(style)
        if not text:
            missing.append(message_id)
        out[message_id] = {**message, "text": text or message.get("text") or ""}
    return out, missing


def capture_extracted() -> tuple[dict, object]:
    """Record what extraction returned per event, so a failed case can show it."""
    from app.extract import real as extract

    original = extract.extract
    captured: dict[str, list[dict]] = {}

    def wrapper(event):
        facts = original(event)
        captured[event.id] = [
            {"type": fact.type, "subject": fact.subject, "data": fact.data, "quote": fact.quote} for fact in facts
        ]
        return facts

    extract.extract = wrapper
    return captured, lambda: setattr(extract, "extract", original)


def call_counter() -> tuple[dict, object]:
    from app.core import llm

    counts = {"calls": 0}
    original = llm.complete_json

    def wrapper(*args, **kwargs):
        counts["calls"] += 1
        return original(*args, **kwargs)

    llm.complete_json = wrapper
    return counts, lambda: setattr(llm, "complete_json", original)


def run_kind(kind: str, data: dict, variants: dict, pipeline_eval, captured: dict) -> dict:
    style = None if kind == "clean" else kind
    library, missing = case_library(data["messages"], variants, style)
    cases = [case for case in data["cases"]
             if not any(entry["msg"] in missing for entry in case["events"])]
    skipped = [case["id"] for case in data["cases"] if case not in cases]
    results = []
    for case in cases:
        captured.clear()
        results.append(pipeline_eval.run_case(case, library))
    failed = []
    for case, result in zip(cases, results):
        if result["passed"]:
            continue
        texts = []
        for entry in case["events"]:
            message = library[entry["msg"]]
            texts.append({"event": entry["id"], "message": entry["msg"],
                          "text": message.get("text") or "", "facts": captured.get(entry["id"], [])})
        failed.append({"case": case["id"], "note": case.get("note", ""), "result": result, "events": texts})
    return {
        "kind": kind,
        "style": style,
        "summary": pipeline_eval.summarize(results, cases),
        "skipped_cases": skipped,
        "skipped_messages": missing,
        "failed": failed,
    }


def render(report: dict) -> str:
    meta, kinds = report["meta"], report["kinds"]
    base = next(item for item in kinds if item["kind"] == "clean")
    lines = [
        "# Detection under messy wording",
        "",
        f"Run at {meta['when']} UTC, mode: {meta['mode']}, model: {meta['model']}. Variants generated "
        f"{meta['variants_generated_at']}.",
        "",
        "The same 22 fixed cases are run once in their clean wording and once per messy style. The expected flags "
        "come from `eval/pipeline/cases.json` and are only compared with, never put into a prompt. Every kind calls "
        "the real model; the clean baseline and every variant answer are replayed from `mocks/llm` when this runs "
        "with `--offline`.",
        "",
        "| Kind | Cases run | Cases passed | Flags expected/found | Missed problems | False alarms | Cases with errors "
        "| Model calls |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in kinds:
        summary = item["summary"]
        calls = item.get("calls", 0)
        lines.append(
            f"| {item['kind']} | {summary['cases']} | {summary['cases_passed']}/{summary['cases']} | "
            f"{summary['expected_flags']}/{summary['flags_found']} | {summary['missed_problems']} | "
            f"{summary['false_alarms']} | {summary['cases_with_errors']} | {calls} |"
        )
    lines += [
        "",
        f"Model calls: {meta['calls']['real']} real (baseline and variants, recorded), "
        f"{meta['calls']['replay']} replayed. Estimate before the run: {meta['estimate']} calls.",
        "",
    ]
    for item in kinds:
        if item["kind"] == "clean":
            continue
        summary = item["summary"]
        lines.append(f"## {item['kind']}")
        lines.append("")
        if item["skipped_cases"]:
            lines.append(f"- Skipped {len(item['skipped_cases'])} case(s) whose message lost a fact when the "
                         f"variant was generated: {', '.join(item['skipped_cases'])}")
        if not item["failed"]:
            lines.append(f"- No failed case: {summary['cases_passed']}/{summary['cases']} passed, "
                         f"{summary['false_alarms']} false alarms.")
        for failed in item["failed"]:
            result = failed["result"]
            lines.append(f"- FAIL `{failed['case']}`: {failed['note']}")
            for missing in result["missed"]:
                lines.append(f"  - missed: {missing['type']} {missing.get('affected', {})}")
            for alarm in result["false_alarms"]:
                lines.append(f"  - false alarm: {alarm['type']} {alarm['id']}: {alarm['title']}")
            for error in result["errors"]:
                lines.append(f"  - error: {error}")
            for event in failed["events"]:
                lines.append(f"  - message `{event['message']}` ({event['event']}): \"{event['text']}\"")
                if not event["facts"]:
                    lines.append("    - extracted nothing")
                for fact in event["facts"]:
                    lines.append(f"    - extracted {fact['type']}: {json.dumps(fact['data'], ensure_ascii=False)}")
        lines.append("")
    lines += [
        "## What this does not test",
        "",
        *[f"- {sentence}" for sentence in LIMITATIONS],
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    from app.core import config

    config.load_dotenv()
    live = "--live" in argv
    record = "--record" in argv
    if not live and not (HERE / "variants.json").is_file():
        sys.exit("run.py: eval/stress/variants.json is missing; run generate.py --live once")
    os.environ["DATA_DIR"] = str(_scratch())
    for name in config.EXTERNAL:
        os.environ.setdefault(f"USE_MOCK_{name.upper()}", "true")
    os.environ["USE_MOCK_LLM"] = "true"
    os.environ.pop("LLM_RECORD", None)
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else HERE
    out.mkdir(parents=True, exist_ok=True)

    data = json.loads((ROOT / "eval" / "pipeline" / "cases.json").read_text(encoding="utf-8"))
    variants = json.loads((HERE / "variants.json").read_text(encoding="utf-8"))
    pipeline_eval = load_pipeline_eval()

    events_per_kind = {kind: sum(len(case["events"]) for case in data["cases"]) for kind in KINDS}
    estimate = sum(events_per_kind[kind] for kind in KINDS)
    estimate = int(estimate + estimate * REPAIR_MARGIN)
    print(f"run: {len(data['cases'])} cases, {len(KINDS)} kinds, estimated {estimate} model calls")

    captured, restore_extract = capture_extracted()
    counts, restore_llm = call_counter()
    report = {"meta": {"when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "mode": "",
                       "model": os.environ.get("LLM_MODEL") or "not set",
                       "variants_generated_at": variants.get("generated_at", "unknown"),
                       "estimate": estimate, "calls": {"real": 0, "replay": 0}},
              "limitations": LIMITATIONS, "kinds": []}
    try:
        for kind in KINDS:
            # Every kind calls the real model with --live --record. The clean baseline included: the committed
            # eval/pipeline recordings were incomplete on main, and this run completes them so the whole report
            # replays offline. The finding itself is on the board.
            os.environ["USE_MOCK_LLM"] = "false" if live else "true"
            if record and live:
                os.environ["LLM_RECORD"] = "true"
            else:
                os.environ.pop("LLM_RECORD", None)
            before = counts["calls"]
            result = run_kind(kind, data, variants, pipeline_eval, captured)
            result["calls"] = counts["calls"] - before
            if record and live:
                report["meta"]["calls"]["real"] += result["calls"]
            else:
                report["meta"]["calls"]["replay"] += result["calls"]
            report["kinds"].append(result)
            summary = result["summary"]
            print(f"{kind:15s} passed {summary['cases_passed']}/{summary['cases']} "
                  f"missed {summary['missed_problems']} false alarms {summary['false_alarms']} "
                  f"calls {result['calls']}")
    finally:
        restore_llm()
        restore_extract()
    report["meta"]["mode"] = ("real model, answers recorded; the clean baseline recordings were completed in this "
                              "run" if live and record else
                              "real model, nothing written to mocks/llm" if live else
                              "replay of the committed recordings")
    (out / "report.md").write_text(render(report), encoding="utf-8", newline="\n")
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8", newline="\n")
    print(f"run: report written to {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
