"""Turn a briefing text into an audio clip, once, without ever raising.

The clip lives under `DATA_DIR/files/briefings`, which the app already serves at `/media/files`. Its name is a
hash of the text and the language, so the same briefing is produced once and every later run reuses it. With the
voice API mocked, a committed sample clip stands in for the service, so tests and the demo never reach the
network. Every character sent to the service is counted against a daily cap, and any failure returns None: a
briefing without a clip still goes out as text.
"""
import hashlib
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.core import config

log = logging.getLogger(__name__)

API = "https://api.elevenlabs.io/v1/text-to-speech"
# ElevenLabs' "Sarah" voice (mature, reassuring, confident), used unless ELEVENLABS_VOICE_ID names another one.
DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
MODEL_ID = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_128"
TIMEOUT_SECONDS = 20
DAILY_CAP_DEFAULT = 40000
FIXTURE = Path(__file__).parent / "fixture" / "briefing.mp3"
BRIEFINGS = "briefings"
RETRY_STATUS = {429, 500, 502, 503, 504}
_lock = threading.Lock()


class SpeechError(Exception):
    pass


def _service_mocked() -> bool:
    return config.external_is_mock("voice_api")


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("SPEECH_DAILY_CHARS") or DAILY_CAP_DEFAULT))
    except ValueError:
        return DAILY_CAP_DEFAULT


def clip_key(text: str, language: str) -> str:
    raw = f"{(language or 'en').strip().lower()}\n{text.strip()}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def clip_url(key: str) -> str:
    return f"/media/files/{BRIEFINGS}/{key}.mp3"


def _folder() -> Path:
    path = config.data_dir() / "files" / BRIEFINGS
    path.mkdir(parents=True, exist_ok=True)
    return path


def _usage_path() -> Path:
    path = config.data_dir() / "speech"
    path.mkdir(parents=True, exist_ok=True)
    return path / "usage.json"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def used_today() -> int:
    """Characters already sent to the service today."""
    path = _usage_path()
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int(data.get("chars") or 0) if data.get("date") == _today() else 0


def _count(chars: int) -> int:
    path = _usage_path()
    total = used_today() + chars
    with _lock:
        path.write_text(json.dumps({"date": _today(), "chars": total}) + "\n", encoding="utf-8")
    return total


def _call(text: str, language: str) -> bytes:
    key = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    if not key:
        raise SpeechError("ELEVENLABS_API_KEY is not set")
    voice = (os.environ.get("ELEVENLABS_VOICE_ID") or "").strip() or DEFAULT_VOICE_ID
    body: dict = {"text": text, "model_id": MODEL_ID}
    if (language or "en").lower()[:2] != "en":
        body["language_code"] = (language or "en").lower()[:2]
    request = urllib.request.Request(
        f"{API}/{voice}?output_format={OUTPUT_FORMAT}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            audio = response.read()
    except urllib.error.HTTPError as error:
        raise SpeechError(f"text to speech refused with HTTP {error.code}") from None
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise SpeechError(f"text to speech unreachable: {type(reason).__name__}") from None
    if not audio:
        raise SpeechError("text to speech returned no audio")
    return audio


def speak(text: str, language: str = "en") -> str | None:
    """The URL of a clip of `text` in `language`, or None when it could not be made."""
    text = (text or "").strip()
    if not text:
        return None
    key = clip_key(text, language)
    path = _folder() / f"{key}.mp3"
    if path.is_file():
        log.info("speech: clip %s already exists, not calling the service again", key)
        return clip_url(key)
    if _service_mocked():
        if not FIXTURE.is_file():
            log.warning("speech: the sample clip is missing at %s, briefing sent as text", FIXTURE)
            return None
        path.write_bytes(FIXTURE.read_bytes())
        log.info("speech: sample clip %s written for a mocked voice API", key)
        return clip_url(key)
    cap = daily_cap()
    if used_today() + len(text) > cap:
        log.warning("speech: daily cap of %d characters reached, briefing sent as text", cap)
        return None
    try:
        audio = _call(text, language)
    except SpeechError as error:
        log.warning("speech: no clip for %s: %s", key, error)
        return None
    path.write_bytes(audio)
    total = _count(len(text))
    log.info("speech: %d characters sent, %d of %d used today", len(text), total, cap)
    return clip_url(key)
