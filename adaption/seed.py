"""Seed a running Aurora with the curated history: one command for the hosted demo.

    uv run --directory backend python ../adaption/seed.py --base-url http://127.0.0.1:8000
    uv run --directory backend python ../adaption/seed.py --base-url https://... --day0 2026-11-14

Rows are posted to POST /api/ingest in the order the event file sorts by day and time, so the record reads as the
week before the demo. `--day0` is the server's own anchor day, the day the history's day 0 falls on: `today`
(the default, which needs DEMO_ANCHOR=today on the server) or YYYY-MM-DD. Seeding is safe to run twice: the
pipeline answers `duplicate` for an event id it already has, and the run prints how many were new.
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import rows

HERE = Path(__file__).resolve().parent
HISTORY = HERE / "history.json"


def post(base_url: str, event: dict) -> dict:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/ingest",
        data=json.dumps(event).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str]) -> int:
    def value(name: str) -> str | None:
        return argv[argv.index(name) + 1] if name in argv else None

    base_url = value("--base-url")
    if not base_url:
        print(__doc__)
        return 2
    day0 = rows.anchor_day(value("--day0"))
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    ordered = sorted(history["rows"], key=lambda row: (row["day"], row["time"], row["id"]))
    print(f"{len(ordered)} rows, day 0 is {day0.isoformat()}, seeding {base_url}")
    counts: dict[str, int] = {}
    for row in ordered:
        event = rows.to_event(row, day0)
        try:
            result = post(base_url, event)
        except urllib.error.HTTPError as error:
            print(f"FAIL {row['id']}: {error.code} {error.read()[:400]!r}")
            return 1
        except urllib.error.URLError as error:
            print(f"FAIL {row['id']}: {error.reason}")
            return 1
        state = "duplicate" if result.get("duplicate") else "ingested"
        counts[state] = counts.get(state, 0) + 1
        print(f"  {row['id']} {event['sent_at']} {row['channel']:8s} {row['sender']:26s} {state}")
    print(f"done: {counts.get('ingested', 0)} new, {counts.get('duplicate', 0)} already there")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
