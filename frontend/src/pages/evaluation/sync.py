"""Copy the committed evaluation reports into this page's folder and build the one bundle the page reads.

The page shows only what the reports say, so it reads copies of its own folder rather than reaching into /eval at
build time. A report that was never run is written as null, and the page shows "Not run yet" for it.

  python frontend/src/pages/evaluation/sync.py          write the copies and data.json
  python frontend/src/pages/evaluation/sync.py --check  fail when a copy differs from its source

The check runs as an e2e step, so a report that changes on main without a re-sync fails the merge instead of showing
stale numbers in the app.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
REPORTS = HERE / "reports"
PIPELINE = ROOT / "eval" / "pipeline" / "report.json"
PIPELINE_MD = ROOT / "eval" / "pipeline" / "report.md"
STRESS = ROOT / "eval" / "stress" / "report.json"
VOICE = ROOT / "eval" / "voice" / "report.json"
SOURCES = {"pipeline": PIPELINE, "stress": STRESS, "voice": VOICE}
LIMITATIONS_HEADING = "## What this does not test"


def _read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _limitations() -> list[str]:
    """The 'What this does not test' bullets of the pipeline report, which only the markdown carries."""
    if not PIPELINE_MD.is_file():
        return []
    lines, found = [], False
    for line in PIPELINE_MD.read_text(encoding="utf-8").splitlines():
        if line.strip() == LIMITATIONS_HEADING:
            found = True
            continue
        if found and line.startswith("## "):
            break
        if found and line.strip().startswith("- "):
            lines.append(re.sub(r"\s+", " ", line.strip()[2:]).strip())
    return lines


def bundle() -> tuple[dict[str, str], str]:
    """The copies to write (name -> exact text or 'null') and the data.json the page imports."""
    copies: dict[str, str] = {}
    data: dict[str, object] = {}
    for name, source in SOURCES.items():
        report = _read(source)
        if report is None:
            copies[name] = "null\n"
            data[name] = None
            continue
        text = source.read_text(encoding="utf-8")
        copies[name] = text if text.endswith("\n") else text + "\n"
        data[name] = report
    pipeline = data.get("pipeline")
    if isinstance(pipeline, dict):
        data["pipeline"] = {**pipeline, "limitations": _limitations()}
    return copies, json.dumps(data, indent=1, sort_keys=True) + "\n"


def _head() -> str | None:
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        return done.stdout.strip() or None
    except Exception:
        return None


def _measured_commit() -> str | None:
    report = _read(PIPELINE)
    if not isinstance(report, dict):
        return None
    meta = report.get("meta")
    return meta.get("commit") if isinstance(meta, dict) else None


def _same(current: str | None, wanted: str) -> bool:
    """Compare the content, not the bytes: a Windows checkout writes CRLF where the generator writes LF."""
    if current is None:
        return False
    try:
        return json.loads(current) == json.loads(wanted)
    except ValueError:
        return current == wanted


def main() -> int:
    copies, data = bundle()
    check = "--check" in sys.argv[1:]
    stale = []
    for name, text in copies.items():
        path = REPORTS / f"{name}.json"
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if not _same(current, text):
            stale.append(str(path.relative_to(ROOT)))
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
    data_path = REPORTS / "data.json"
    current = data_path.read_text(encoding="utf-8") if data_path.is_file() else None
    if not _same(current, data):
        stale.append(str(data_path.relative_to(ROOT)))
        if not check:
            data_path.parent.mkdir(parents=True, exist_ok=True)
            data_path.write_text(data, encoding="utf-8", newline="\n")
    if check:
        if stale:
            print("evaluation reports are stale, run frontend/src/pages/evaluation/sync.py:", ", ".join(stale),
                  file=sys.stderr)
            return 1
        measured, head = _measured_commit(), _head()
        if measured and head and measured != head:
            print(f"evaluation numbers were measured on commit {measured[:12]}, HEAD is {head[:12]}")
        elif not measured:
            print("the evaluation report does not name the commit its numbers were measured on")
        print("evaluation reports are up to date")
        return 0
    print("evaluation reports up to date" if not stale else "wrote " + ", ".join(stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
