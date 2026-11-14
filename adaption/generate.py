"""One Adaption run: the scenario messages in, routine site messages in the same style out.

    uv run --with adaption==0.19.0 python adaption/generate.py source             write source.jsonl, no network
    uv run --with adaption==0.19.0 python adaption/generate.py estimate --rows N  upload source.jsonl, price N rows
    uv run --with adaption==0.19.0 python adaption/generate.py run --rows N       generate N rows, download them

`estimate` creates the source dataset (raw upload, no adaptation) and asks for a quote with estimate=true, which
starts nothing. `run` reuses that dataset and an idempotency key, so a retried run is never charged twice. Both
append what happened to run.json: `estimates` and `runs` hold every quote and every paid run of this source. The
key comes from ADAPTION_API_KEY in the environment or the repo's .env and is never printed.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import rows

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "source.jsonl"
GENERATED = HERE / "generated.jsonl"
RUN = HERE / "run.json"


def load_key() -> None:
    env = rows.ROOT / ".env"
    if "ADAPTION_API_KEY" in os.environ or not env.is_file():
        return
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        key, _, value = line.strip().partition("=")
        if key.strip() == "ADAPTION_API_KEY" and value.strip():
            os.environ["ADAPTION_API_KEY"] = value.strip().strip("'\"")


def client():
    from adaption import Adaption

    load_key()
    if not os.environ.get("ADAPTION_API_KEY"):
        sys.exit("Set ADAPTION_API_KEY in .env.")
    return Adaption(max_retries=1)


def state() -> dict:
    data = json.loads(RUN.read_text(encoding="utf-8")) if RUN.is_file() else {}
    data.setdefault("estimates", [])
    data.setdefault("runs", [])
    return data


def save(update: dict) -> dict:
    data = {**state(), **update}
    RUN.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return data


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_source() -> int:
    source = rows.source_rows()
    rows.write_jsonl(SOURCE, source)
    print(f"wrote {SOURCE.name}: {len(source)} rows")
    return 0


def cmd_estimate(count: int) -> int:
    api = client()
    known = state()
    if known.get("source_dataset_id"):
        dataset_id = known["source_dataset_id"]
    else:
        upload = api.datasets.upload_file(SOURCE, name="maple-court-scenario-messages", processing_mode="raw",
                                          column_mapping={"prompt": "prompt", "completion": "completion"})
        dataset_id = upload.dataset_id
        save({"source_dataset_id": dataset_id, "source_rows": len(rows.read_jsonl(SOURCE)), "uploaded_at": now()})
    status = api.datasets.wait_for_completion(dataset_id, timeout=600)
    print(f"source dataset {dataset_id}: {status.status}, {status.row_count} rows")
    quote = api.datasets.augment(dataset_id, similar_rows=count, estimate=True)
    save({"estimates": [*state()["estimates"], {"similar_rows": count, "credits": quote.estimated_credits_consumed,
                                                "at": now()}]})
    print(f"estimate for {count} generated rows: {quote.estimated_credits_consumed} credits (nothing started)")
    return 0


def cmd_run(count: int) -> int:
    api = client()
    known = state()
    if not known.get("source_dataset_id"):
        sys.exit(f"run `estimate --rows {count}` first, so the cost is known before anything is charged")
    estimate = next((item for item in reversed(known["estimates"]) if item["similar_rows"] == count), None)
    if estimate is None:
        sys.exit(f"run `estimate --rows {count}` first, so the cost is known before anything is charged")
    result = api.datasets.augment(known["source_dataset_id"], similar_rows=count,
                                  idempotency_key=f"maple-court-history-{count}")
    entry = {"similar_rows": count, "dataset_id": result.dataset_id, "status": result.status,
             "credits": result.estimated_credits_consumed, "started_at": now()}
    save({"runs": [*state()["runs"], entry]})
    print(f"run started: dataset {result.dataset_id}, {result.estimated_credits_consumed} credits")
    status = api.datasets.wait_for_completion(result.dataset_id, timeout=3600)
    print(f"run finished: {status.status}, {status.row_count} rows")
    entry.update(status=status.status, row_count=status.row_count, finished_at=now())
    if status.status != "succeeded":
        message = status.error_data.message if status.error_data else "no error message"
        save({"runs": [*state()["runs"][:-1], {**entry, "error": message}]})
        sys.exit(f"run did not succeed: {message}")
    body = api.datasets.download(result.dataset_id, file_format="jsonl").read()
    GENERATED.write_bytes(body)
    downloaded = len(rows.read_jsonl(GENERATED))
    save({"runs": [*state()["runs"][:-1], {**entry, "downloaded_rows": downloaded}]})
    print(f"downloaded {downloaded} rows to {GENERATED.name}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("source", "estimate", "run"):
        print(__doc__)
        return 2
    count = int(argv[argv.index("--rows") + 1]) if "--rows" in argv else 0
    if argv[0] != "source" and count <= 0:
        sys.exit("--rows N is required and must be positive")
    return {"source": cmd_source, "estimate": lambda: cmd_estimate(count), "run": lambda: cmd_run(count)}[argv[0]]()
