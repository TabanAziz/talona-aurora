"""Measured independence: how much of the prepared history Aurora handles without a human.

    uv run --directory backend python ../eval/autonomy/run.py
        Replay every history row through the app's own pipeline, answers from mocks/llm. Offline, free.

    uv run --directory backend python ../eval/autonomy/run.py --live
        Print what a real-model run would cost and stop. Nothing is spent.

    uv run --directory backend python ../eval/autonomy/run.py --live --confirm
        The same estimate, then the real model. Add --record to keep the answers as replay files.

Options: --out <folder for report.md and report.json> (default this folder).

The run writes a ledger of what the pipeline did with every row and a summary scored from it. Scoring is a pure
function of the ledger, so test_report.py re-scores the committed ledger offline and must get the same numbers.
"""
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "adaption"))

# Published prices per million tokens for the models this key serves, read from the provider's price page on
# 2026-11-13. Only used for the estimate printed before a live run; the report never states a cost.
PRICES = {
    "deepseek-v4-1-flash-1017": (0.30, 1.20),
    "mistral-small-2603": (0.15, 0.60),
    "mistral-large-2512": (0.70, 2.10),
}
SECONDS_PER_CALL = 2.0
TOKENS_IN_PER_CALL = 900
TOKENS_OUT_PER_CALL = 200


def prepared_history() -> tuple[list, date]:
    """The rows of adaption/history.json as inbound events, in the order the demo seeds them."""
    import rows

    from app.core import models as m

    data = json.loads((ROOT / "adaption" / "history.json").read_text(encoding="utf-8"))
    day0 = rows.anchor_day(None)
    ordered = sorted(data["rows"], key=lambda row: (row["day"], row["time"], row["id"]))
    return [m.InboundEvent.model_validate(rows.to_event(row, day0)) for row in ordered], day0


def demo_events():
    """The demo's own events, played after the history the way the demo plays them.

    They are reported separately and never mixed into the history's numbers: the history is built to raise no
    flag, and these are the events that do.
    """
    from app.core import models as m

    data = json.loads((ROOT / "mocks" / "scenario.json").read_text(encoding="utf-8"))
    events = [m.InboundEvent.model_validate(raw) for raw in data.get("events", [])]
    return sorted(events, key=lambda event: event.received_at)


def message_kind(message) -> str:
    reason = (getattr(message, "reason", "") or "").strip()
    if reason.startswith("Escalation"):
        return "escalation"
    if reason.startswith("Reminder") or reason.startswith("One reminder"):
        return "reminder"
    if reason == "Answer to crew question":
        return "answer_message"
    return "notice"


def observe(event, result) -> dict:
    """One ledger row: what the pipeline did with one history event, in the terms the report counts."""
    not_understood = any((fact.data or {}).get("not_understood") for fact in result.facts)
    facts = len(result.facts)
    return {
        "event": event.id,
        "day": event.sent_at.date().isoformat(),
        "channel": event.channel,
        "sender": event.sender,
        "text_chars": len((event.text or "").strip()),
        "facts": facts,
        "fact_types": [fact.type for fact in result.facts],
        "not_understood": not_understood,
        "flags": [{"id": flag.id, "type": flag.type} for flag in result.flags],
        "messages": [{"id": message.id, "kind": message_kind(message), "status": message.status}
                     for message in result.outbox],
        "answer": None if result.answer is None else {
            "id": result.answer.id, "basis": result.answer.basis, "escalated": result.answer.escalated,
        },
        "error": None,
    }


def replay(events) -> list[dict]:
    from app.core import pipeline

    pipeline.reset()
    ledger = []
    for event in events:
        try:
            result = pipeline.ingest(event)
            ledger.append(observe(event, result))
        except Exception as error:  # a failure is a result of this row, not a crash of the whole run
            ledger.append({
                "event": event.id, "day": event.sent_at.date().isoformat(), "channel": event.channel,
                "sender": event.sender, "text_chars": len((event.text or "").strip()), "facts": 0,
                "not_understood": True, "flags": [], "messages": [], "answer": None,
                "error": f"{type(error).__name__}: {error}",
            })
    return ledger


def readiness_checks(ledger: list[dict]) -> list[dict]:
    """The start checks Aurora runs on its own for one day of the history, the way the daily readiness run does."""
    from app.core.registry import area

    days = sorted({row["day"] for row in ledger})
    checks = []
    for day in days:
        try:
            readiness = area("readiness").evaluate(date.fromisoformat(day))
            items = list(getattr(readiness, "items", []) or [])
            checks.append({
                "day": day,
                "checked": len(items),
                "statuses": dict(Counter(item.status for item in items)),
            })
        except Exception as error:
            checks.append({"day": day, "checked": 0, "statuses": {}, "error": f"{type(error).__name__}: {error}"})
    return checks


def score(ledger: list[dict], checks: list[dict]) -> dict:
    """The numbers of the report, computed from the ledger alone so the test can repeat it."""
    kinds = Counter()
    for row in ledger:
        for message in row["messages"]:
            kinds[message["kind"]] += 1
        if row["answer"] is not None:
            basis = row["answer"]["basis"]
            kinds[f"answer_from_{basis}"] += 1
    start_checks = sum(check["checked"] for check in checks)
    kinds["start_check"] = start_checks

    flags = Counter()
    for row in ledger:
        for flag in row["flags"]:
            flags[flag["type"]] += 1
    fact_types = Counter()
    for row in ledger:
        for name in row.get("fact_types") or []:
            fact_types[name] += 1
    not_understood = [row["event"] for row in ledger if row["not_understood"]]
    errors = [row["event"] for row in ledger if row.get("error")]

    handled = [row for row in ledger if not row["flags"] and not row["not_understood"]]
    passed = [row for row in ledger if row["flags"] or row["not_understood"]]
    # The message that carries an answer is part of that answer, not a second action.
    actions = sum(kinds[kind] for kind in ("notice", "reminder", "escalation",
                                           "answer_from_record", "answer_from_standing_rule", "start_check"))
    human_decisions = sum(flags.values()) + len(not_understood)
    return {
        "events": len(ledger),
        "events_handled_without_a_human": len(handled),
        "events_passed_to_a_human": len(passed),
        "dates": len({row["day"] for row in ledger}),
        "messages_not_understood": len(not_understood),
        "events_with_an_error": len(errors),
        "error_events": errors,
        "not_understood_events": not_understood,
        "facts_total": sum(fact_types.values()),
        "facts_by_type": {name: count for name, count in sorted(fact_types.items()) if count},
        "actions_taken_by_aurora": actions,
        # The message that carries an answer is not shown as a kind: the answer is counted once, below.
        "actions_by_kind": {kind: kinds[kind] for kind in sorted(kinds)
                            if kinds[kind] and kind != "answer_message"},
        "cases_passed_to_a_human_by_kind": {
            **{f"flag_{kind}": count for kind, count in sorted(flags.items())},
            **({"not_understood": len(not_understood)} if not_understood else {}),
        },
        "human_decisions_required": human_decisions,
        "share_events_without_a_human": f"{len(handled)} of {len(ledger)}",
        "share_actions_without_a_human": f"{actions} of {actions + human_decisions}",
        "start_checks_by_day": checks,
    }


def render(summary: dict, meta: dict, demo: dict) -> str:
    kinds = summary["actions_by_kind"]
    passed = summary["cases_passed_to_a_human_by_kind"]
    facts = ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in summary["facts_by_type"].items())
    demo_rows = "\n".join(f"| {name.replace('_', ' ')} | {count} |"
                          for name, count in demo["actions_by_kind"].items()) or "| nothing | 0 |"
    rows = "\n".join(f"| {name.replace('_', ' ') } | {count} |" for name, count in kinds.items())
    human = "\n".join(f"| {name.replace('flag_', 'flag, ').replace('_', ' ')} | {count} |"
                      for name, count in passed.items()) or "| nothing | 0 |"
    days = "\n".join(
        f"| {check['day']} | {check['checked']} | "
        + ", ".join(f"{status} {count}" for status, count in sorted(check["statuses"].items()))
        + " |"
        for check in summary["start_checks_by_day"]
    )
    return f"""# Measured independence

Run at {meta['when']} UTC, mode: {meta['mode']}, model: {meta['model']}.
Prepared history: {summary['events']} events over {summary['dates']} days, day 0 is {meta['day0']}.
Areas with a real module: {', '.join(meta['real_areas'])}. Areas still on their mock:
{', '.join(meta['mock_areas']) or 'none'}.

Every row of `adaption/history.json` is converted to an inbound event exactly as the demo seeds it
(`adaption/rows.py`, same delivery delays) and replayed in order through `pipeline.ingest`, the one entry point
the app uses. Nothing is reimplemented: the flags, notices, reminders, escalations, answers and start checks
counted here are the ones the running app produced. The model answers were recorded once with
`--live --confirm --record` and committed under `mocks/llm/`, so this file runs again offline and gives the same
numbers.

## The number

| Measure | Result |
|---|---|
| Events in the prepared history | {summary['events']} |
| Events Aurora handled without a human decision | {summary['share_events_without_a_human']} |
| Events it passed to a human | {summary['events_passed_to_a_human']} |
| Actions Aurora took on its own | {summary['actions_taken_by_aurora']} |
| Human decisions the history still required | {summary['human_decisions_required']} |
| Actions without a human, out of actions plus human decisions | {summary['share_actions_without_a_human']} |

## Actions Aurora took on its own

{rows}

The history's {summary['facts_total']} facts were {facts}, so this is a week of work announcements and schedule
updates, not a week of problems: the extraction had nothing to flag. The demo's problems are the block below.

## What it passed to a human

{human}

## The demo's own events, for comparison

The prepared history is built to raise no flag, open no waiting item, answer no question and send no message
(`adaption/README.md`, the curation checks), so the history's share is a check on that promise. The problems the
demo shows are its own events. Playing them after the history, with the same counting:

| Measure | Result |
|---|---|
| Events | {demo['events']} |
| Events Aurora handled without a human decision | {demo['share_events_without_a_human']} |
| Events it passed to a human | {demo['events_passed_to_a_human']} |
| Actions Aurora took on its own | {demo['actions_taken_by_aurora']} |
| Human decisions the events required | {demo['human_decisions_required']} |
| Messages not understood | {demo['messages_not_understood']} |

What Aurora did on those events, by kind:

{demo_rows}

This is the number earned autonomy changes, and it is not this feature's measurement: today every flag needs a
superintendent decision, and the block above is what that costs.

## Start checks it ran by day

| Day | Checks | Statuses |
|---|---|---|
{days}

## How each number is counted

- **Event**: one row of `adaption/history.json`, replayed through `pipeline.ingest`. Duplicates do not exist
  because every row has its own id.
- **Handled without a human decision**: the event raised no flag and was not marked not understood. It needed no
  superintendent decision. An event that produced a notice is still handled; the notice is counted as an action.
- **Passed to a human**: the event raised at least one flag, or the extractor marked it not understood. A flag
  needs a decision (hold, release, reschedule, dismiss); a message not understood needs a person to clarify.
- **Human decisions required**: one per flag raised plus one per message not understood. A flag is counted once,
  by the event that raised it.
- **Actions taken on its own**: every outbound message the pipeline delivered while replaying (notices,
  reminders, escalations), every answer `qa` returned, and every start check the readiness run performed for the
  days of the history. The message that carries an answer is part of that answer and is counted once, through the
  answer. Read-back messages are counted as notices.
- **Start check**: one per task the readiness run evaluates for a day of the history. The checks run with the
  real gate, so they answer from the plan, flags and standing rules, with no model call.
- **Share**: always both numbers, the handled count and the total, never a percentage on its own.

## What this does not measure

- It does not measure whether Aurora was right. There is no expected answer per history row; detection quality is
  `eval/pipeline` and noise robustness is `eval/stress`.
- It does not measure the future with earned autonomy switched on. The history is measured with today's rules,
  where every flag still needs a superintendent decision. The number to quote for "earned autonomy" is a second
  run of this file after the autonomy mechanism lands, and the difference between the two.
- A crew confirmation is not a superintendent decision: reminders and escalations are counted as actions, and the
  confirmation they ask for is not counted as human work here.
- Recorded model answers are used by default, so the facts are those of the recorded run, not of a fresh model.
  `--live` repeats the same measurement with the real model.
- Voice notes are not in this history; every row is text, email or a schedule update.
- The channels are mocked and delivery is simulated, so no message actually leaves the app.
- The history is synthetic: 60 team-written rows plus Adaption-generated ones. The counts show what the prepared
  history contains, not a rate on real site traffic.
"""


def estimate(events) -> str:
    model = os.environ.get("LLM_MODEL") or "not set"
    extracting = sum(1 for event in events if (event.text or "").strip())
    calls = extracting * 2  # one extraction per message, plus an upper bound of one answer for each
    seconds = calls * SECONDS_PER_CALL
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    usd = calls * (TOKENS_IN_PER_CALL / 1e6 * price_in + TOKENS_OUT_PER_CALL / 1e6 * price_out)
    cost = f"about {usd:.2f} USD" if price_in else "unknown model, no price on file"
    return (f"live estimate: {calls} model calls ({extracting} extractions and an upper bound of {extracting} "
            f"answers), about {seconds / 60:.1f} minutes at {SECONDS_PER_CALL:.0f} s per call, {cost}. "
            f"Nothing was spent. Run again with --confirm to spend it.")


def main(argv: list[str]) -> int:
    from app.core import config

    config.load_dotenv()
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="aurora-autonomy-")
    for name in config.EXTERNAL:
        os.environ.setdefault(f"USE_MOCK_{name.upper()}", "true")
    live = "--live" in argv
    if live:
        os.environ["USE_MOCK_LLM"] = "false"
    if "--record" in argv:
        os.environ["LLM_RECORD"] = "true"

    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else HERE
    events, day0 = prepared_history()

    if live and "--confirm" not in argv:
        print(estimate(events))
        return 2

    from app.core import registry

    started = datetime.now(timezone.utc)
    ledger = replay(events)
    checks = readiness_checks(ledger)
    summary = score(ledger, checks)
    demo_ledger = replay(demo_events())
    demo_summary = score(demo_ledger, readiness_checks(demo_ledger))
    real = [name for name in config.AREAS if not registry.is_mock(name)]
    meta = {
        "when": started.strftime("%Y-%m-%d %H:%M"),
        "mode": "real model" if live else "replay of recorded model answers",
        "model": os.environ.get("LLM_MODEL") or "not set",
        "day0": day0.isoformat(),
        "history": "adaption/history.json",
        "real_areas": real,
        "mock_areas": [name for name in config.AREAS if name not in real],
        "estimate": estimate(events) if live else None,
    }
    (out / "report.json").write_text(
        json.dumps({"meta": meta, "summary": summary, "ledger": ledger,
                    "demo": {"summary": demo_summary, "ledger": demo_ledger}}, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    (out / "report.md").write_text(render(summary, meta, demo_summary), encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))
    return 1 if summary["events_with_an_error"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
