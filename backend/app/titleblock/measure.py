"""The deliberate real-model run over the fixed photo set: nine photos, one call each.

    uv run --directory backend python -m app.titleblock.measure --record    real model, records the answers
    uv run --directory backend python -m app.titleblock.measure             replay only, prints the same table

It goes through the area's own code path (`inspect`, then `react`), not around it, so the measurement covers the
normalisation, the acceptance rules and the wording. With `--record` the answers are written to `mocks/llm/` and
committed; without it the committed answers are replayed, so the table can be printed offline.
"""
import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "docs" / "photo" / "fixtures"

# What each photo shows and what the read must be. None means "must not be accepted".
EXPECTED: dict[str, tuple[str, str] | None] = {
    "photo_a201_rev_c_flat.jpg": ("A-201", "C"),
    "photo_a201_rev_c_angle.jpg": ("A-201", "C"),
    "photo_e201_rev_b_angle.jpg": ("E-201", "B"),
    "photo_a201_rev_b_angle.jpg": ("A-201", "B"),
    "photo_a201_rev_b_dark.jpg": ("A-201", "B"),
    "photo_e201_rev_a_angle.jpg": ("E-201", "A"),
    "photo_a201_rev_b_blurred.jpg": ("A-201", "B"),
    "photo_a201_no_revision.jpg": None,
    "photo_not_a_sheet.jpg": None,
}


def run(record: bool) -> int:
    data_dir = tempfile.mkdtemp(prefix="aurora-titleblock-")
    os.environ["DATA_DIR"] = data_dir
    from app.core import config

    for name in config.AREAS:
        os.environ[f"USE_MOCK_{name.upper()}"] = "true"
    os.environ["USE_MOCK_TITLEBLOCK"] = "false"
    os.environ["USE_MOCK_RECORD"] = "false"
    for name in ("VOICE_API", "TELEGRAM_API", "EMAIL_API", "WHATSAPP_API"):
        os.environ[f"USE_MOCK_{name}"] = "true"
    os.environ["USE_MOCK_LLM"] = "false" if record else "true"
    os.environ["LLM_RECORD"] = "true" if record else "false"
    if record:
        config.load_dotenv()

    from app.core import llm, pipeline
    from app.core import models as m
    from app.titleblock import real

    photos = Path(data_dir) / "files" / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, expected in EXPECTED.items():
        source = FIXTURES / name
        shutil.copyfile(source, photos / name)
        pipeline.reset()
        event = m.InboundEvent(
            id=f"photo-{name}", channel="telegram", sender="Marco Ruiz", sender_role="Framing foreman",
            sent_at="2026-11-13T09:00:00Z", received_at="2026-11-13T09:00:05Z", text="",
            attachments=[m.Attachment(kind="image", name=name, url=f"/media/files/photos/{name}",
                                      media_type="image/jpeg")],
        )
        started = time.monotonic()
        facts = real.inspect(event)
        message = real.react(event, facts)
        seconds = time.monotonic() - started
        fact = facts[0] if facts else None
        data = fact.data if fact else {}
        read = (data.get("sheet"), data.get("revision")) if data.get("status") == "read" else None
        text = (message[0].text if message else "").split(".")[0]
        if expected is None:
            correct = read is None
        elif name.endswith("blurred.jpg"):
            correct = read == expected or read is None
        else:
            correct = read == expected
        rows.append({
            "photo": name, "expected": expected, "read": read, "status": data.get("status"),
            "reason": data.get("reason"), "model": data.get("model"), "seconds": round(seconds, 2),
            "correct": correct, "wrong_revision": read is not None and read != expected,
            "text": text,
        })
        print(f"{name:34s} expected {str(expected):14s} read {str(read):14s} "
              f"{data.get('status') or '-':8s} {data.get('reason') or '-':18s} {seconds:5.2f}s", flush=True)

    seconds = [row["seconds"] for row in rows]
    summary = {
        "model": rows[0]["model"],
        "cases": len(rows),
        "expected_answers": sum(1 for row in rows if row["correct"]),
        "wrong_revisions": sum(1 for row in rows if row["wrong_revision"]),
        "could_not_read": sum(1 for row in rows if row["status"] != "read"),
        "median_seconds": round(statistics.median(seconds), 2),
        "worst_seconds": max(seconds),
    }
    print(json.dumps(summary, indent=2))
    (Path(data_dir) / "measure-run.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2),
                                                     encoding="utf-8")
    return 0 if summary["wrong_revisions"] == 0 else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--record", action="store_true", help="call the real model and keep the answers")
    return run(parser.parse_args(argv).record)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
