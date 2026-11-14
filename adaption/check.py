"""Check history.json: the rows themselves, then the rows through a sandbox copy of the pipeline.

    uv run --directory backend python ../adaption/check.py
    uv run --directory backend python ../adaption/check.py --record   fill missing answers with the real model

The sandbox is a fresh DATA_DIR with every external service forced to its mock, so nothing is sent anywhere and
no live mailbox or bot is touched. DEMO_ANCHOR is ignored, so the rows sit on the scenario's own days and the
recorded answers stay valid. Every model answer is replayed from mocks/llm or from llm/ here; `--record` asks the
real model only for the answers that are not there yet and saves them, which is the only mode that needs a key.

It passes when every row is usable (rows.problems), every crew has at least three messages, at least twelve
units are named, no row is left not understood, the history alone raises no flag, opens no waiting item, answers
no question and sends no message, and the scenario ends with the same flags and waiting items with and without
the history in front of it. Exit code 0 only then.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))

import rows  # noqa: E402  (needs the path above)

HISTORY = HERE / "history.json"
RECORDED = HERE / "llm"
MIN_ROWS = 30
MIN_PER_CREW = 3
MIN_UNITS = 12


def sandbox() -> tuple[Path, set[str]]:
    from app.core import config, llm

    os.environ.pop("DEMO_ANCHOR", None)
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="aurora-adaption-")
    # Assigned, not setdefault: the repo .env may switch live services on, and this run must never reach them.
    for name in config.EXTERNAL:
        os.environ[f"USE_MOCK_{name.upper()}"] = "true"
    os.environ["USE_MOCK_LLM"] = "true"
    os.environ["LLM_RECORD"] = "false"

    # The demo path's answers live in mocks/llm and the ones only this check needs in llm/; both are replayed.
    replay = Path(os.environ["DATA_DIR"]) / "llm"
    replay.mkdir()
    for folder in (llm.REPLAY_DIR, RECORDED):
        for path in folder.glob("*.json") if folder.is_dir() else []:
            shutil.copy2(path, replay / path.name)
    shared = {p.name for p in llm.REPLAY_DIR.glob("*.json")}
    llm.REPLAY_DIR = replay
    return replay, shared


def fill_gaps(replay: Path) -> None:
    """Replay an answer the sandbox already has, ask the model for a missing one and keep it.

    A missing recording is a developer error the pipeline must not swallow, so a failed call is retried here
    and only then raised; a burst of calls is rate limited often enough to make one attempt useless.
    """
    from app.core import config, llm

    config.load_dotenv()

    def complete(*, system: str, user: str, schema: dict) -> dict:
        path = replay / f"{llm._key(system, user, schema)}.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))["answer"]
        for attempt in range(1, 4):
            try:
                answer = llm._call(system, user, schema)
                break
            except llm.LLMError:
                if attempt == 3:
                    raise
                time.sleep(5)
        path.write_text(json.dumps({"system": system, "user": user, "answer": answer}, indent=2, sort_keys=True)
                        + "\n", encoding="utf-8")
        return answer

    llm.complete_json = complete


def keep_new(replay: Path, before: set[str]) -> int:
    RECORDED.mkdir(exist_ok=True)
    saved = 0
    for path in replay.glob("*.json"):
        if path.name not in before and not (RECORDED / path.name).is_file():
            shutil.copy2(path, RECORDED / path.name)
            saved += 1
    return saved


def check_rows(history: dict, known: dict) -> list[str]:
    errors = []
    items = history["rows"]
    if len(items) < MIN_ROWS:
        errors.append(f"{len(items)} rows, at least {MIN_ROWS} needed")
    scenario_ids = {e["id"] for e in json.loads((rows.MESSAGES / "events.json").read_text(encoding="utf-8"))}
    seen = set()
    for row in items:
        if row["id"] in scenario_ids or row["id"] in seen:
            errors.append(f"{row['id']}: id is used twice or by the scenario")
        seen.add(row["id"])
        errors += [f"{row['id']}: {p}" for p in rows.problems(row, known)]
    per_crew = Counter(c for row in items for c in {known["senders"].get(row["sender"], {}).get("crew")} if c)
    for crew in known["crews"]:
        if per_crew[crew] < MIN_PER_CREW:
            errors.append(f"{crew} sends {per_crew[crew]} messages, at least {MIN_PER_CREW} needed")
    units = {u for row in items for u in rows.refs(row, known)["units"]}
    if len(units) < MIN_UNITS:
        errors.append(f"{len(units)} units named, at least {MIN_UNITS} needed")
    print(f"rows: {len(items)}, channels: {dict(Counter(r['channel'] for r in items))}")
    print(f"messages per crew foreman: {dict(sorted(per_crew.items()))}")
    print(f"units named: {len(units)} ({', '.join(sorted(units))})")
    return errors


def snapshot() -> dict:
    from app.core.store import store

    s = store()
    return {
        "flags": sorted((f["id"], f["type"], f["status"]) for f in s.list("flags")),
        "waiting": sorted(w["id"] for w in s.list("waiting") if w["status"] == "open"),
        "answers": len(s.list("answers")),
        "outbox": len(s.list("outbox")),
    }


def not_understood(facts: list) -> list[str]:
    return [fact.id for fact in facts if fact.type == "other" and fact.data.get("not_understood")]


def ingest_history(events: list) -> tuple[list[str], list[dict]]:
    """Every history event through the pipeline on an empty store; nothing may come out the other side."""
    from app.core import llm, pipeline

    errors = []
    pipeline.reset()
    before = snapshot()
    try:
        results = [pipeline.ingest(event) for event in events]
    except llm.LLMError as error:
        return [f"{error} (record it with --record)"], before
    for result, event in zip(results, events):
        errors += [f"{event.id}: raises flag {flag.type} {flag.title!r}" for flag in result.flags]
        if result.answer is not None:
            errors.append(f"{event.id}: is answered as a question")
        if result.outbox:
            errors.append(f"{event.id}: sends {len(result.outbox)} message(s)")
    after = snapshot()
    opened = sorted(set(after["waiting"]) - set(before["waiting"]))
    if opened:
        errors.append(f"history opens waiting items: {', '.join(opened)}")
    missing = sorted({f for result in results for f in not_understood(result.facts)})
    if missing:
        errors.append(f"not understood: {', '.join(missing)}")
    open_flags = [f for f in after["flags"] if f[2] == "open"]
    print(f"history alone: {len(after['flags'])} flags ({len(open_flags)} open), "
          f"{len(opened)} new waiting items, {after['answers']} answers, {after['outbox']} outbound messages, "
          f"{len(missing)} not understood")
    return errors, after


def check_pipeline(events: list) -> list[str]:
    from app.core import llm, pipeline
    from app.core.registry import area

    errors, after = ingest_history(events)
    scenario = area("replay").events()
    try:
        pipeline.reset()
        for event in scenario:
            pipeline.ingest(event)
        alone = snapshot()
        pipeline.reset()
        for event in [*events, *scenario]:
            pipeline.ingest(event)
    except llm.LLMError as error:
        return [*errors, f"{error} (record it with --record)"]
    together = snapshot()
    together["answers"] -= after["answers"]
    together["outbox"] -= after["outbox"]
    if alone != together:
        errors.append(f"the scenario ends differently after the history: without {alone}, with {together}")
    print(f"scenario of {len(scenario)} events: {len(alone['flags'])} flags and {len(alone['waiting'])} open "
          f"waiting items without the history, {'the same' if alone == together else 'DIFFERENT'} with it")
    return errors


def main(argv: list[str]) -> int:
    record = "--record" in argv
    replay, shared = sandbox()
    try:
        return check(record, replay, shared)
    finally:
        shutil.rmtree(replay.parent, ignore_errors=True)


def check(record: bool, replay: Path, shared: set[str]) -> int:
    from app import demodata
    from app.core import models as m

    if demodata.SCENARIO_DAY != rows.ANCHOR_DAY:
        print(f"FAIL rows.ANCHOR_DAY {rows.ANCHOR_DAY} differs from app.demodata.SCENARIO_DAY")
        return 1
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    known = rows.project()
    errors = check_rows(history, known)
    events = []
    for row in sorted(history["rows"], key=lambda r: (r["day"], r["time"], r["id"])):
        try:
            events.append(m.InboundEvent.model_validate(rows.to_event(row)))
        except ValueError as error:
            errors.append(f"{row['id']}: not an InboundEvent: {error}")
    if record:
        fill_gaps(replay)
    if not errors:
        errors += check_pipeline(events)
    if record:
        print(f"saved {keep_new(replay, shared)} new model answers to {RECORDED.name}/")
    for error in errors:
        print(f"FAIL {error}")
    print("ok" if not errors else f"{len(errors)} problem(s)")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
