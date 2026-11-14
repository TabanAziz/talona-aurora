"""Print the transcript of audio files, and record the service's answers for offline tests.

    uv run --directory backend python -m app.voice.record FILE...           replay from recordings/
    uv run --directory backend python -m app.voice.record --live FILE...    call ElevenLabs once per file and record

`--live` skips files that already have a recording, so a rerun costs nothing. Every live call uses the
shared quota: run it by hand, never from a test or a loop.
"""
import json
import mimetypes
import os
import sys
import tempfile
import time
from pathlib import Path

from app.core import config


def main(argv: list[str]) -> int:
    live = "--live" in argv
    files = [Path(a) for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    config.load_dotenv()
    # A scratch store with the project loaded, so the call carries the same keyterms as in the app.
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="aurora-voice-")
    if live:
        os.environ["USE_MOCK_VOICE_API"] = "false"
    from app.core import pipeline
    from app.voice import real

    pipeline.ensure_ready()

    failed = 0
    for path in files:
        audio = path.read_bytes()
        target = real.recording_path(audio)
        if target.is_file():
            answer = json.loads(target.read_text(encoding="utf-8"))["answer"]
            print(f"{path.name}\trecorded {target.name}\t{answer['text']}")
            continue
        if not live:
            print(f"{path.name}\tno recording {target.name}")
            failed += 1
            continue
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        started = time.monotonic()
        try:
            answer = real.call_service(audio, path.name, media_type)
        except real.VoiceError as error:
            print(f"{path.name}\tfailed: {error}")
            failed += 1
            continue
        seconds = time.monotonic() - started
        real.RECORDINGS.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"source": path.name, "model_id": real.MODEL_ID, "answer": answer}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"{path.name}\tlive {seconds:.1f}s, saved {target.name}\t{answer['text']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
