"""Speech to text for voice notes, with the ElevenLabs speech-to-text API.

With `USE_MOCK_VOICE_API` unset or true, nothing touches the network: the service's answer for an audio
file is read from `recordings/<key>.json`, keyed by a hash of the audio bytes. A voice note with no audio
file at all gets the stand-in transcript of `mock.py` in that mode. Any failure (no file, no recording,
refusal, timeout) leaves `transcript` empty with a logged reason and text is never guessed; extraction then
keeps the note as not understood, so the record shows it with its sender.

Record answers with `python -m app.voice.record` (see README), never inside a test.
"""
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from app.core import config
from app.core import models as m
from app.core.store import store
from app.voice import mock

log = logging.getLogger(__name__)

API = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL_ID = "scribe_v3"
# The Telegram webhook waits for the pipeline, so one transcription must stay well under its patience.
TIMEOUT_SECONDS = 12
DEADLINE_SECONDS = 25
MAX_AUDIO_BYTES = 25 * 1024 * 1024
RECORDINGS = Path(__file__).parent / "recordings"
RETRY_STATUS = {429, 500, 502, 503, 504}
REVISION_LETTERS = "ABCDEFGH"
# More than 100 keyterms makes every request bill at least 20 seconds.
MAX_KEYTERMS = 100
KEYTERM_FORBIDDEN = set("<>{}[]\\")
MEDIA_ROOTS = (("/media/files/", lambda: config.data_dir() / "files"), ("/media/mock/", lambda: config.ROOT / "mocks" / "assets"))


class VoiceError(Exception):
    pass


class _Retryable(VoiceError):
    pass


def _mocked() -> bool:
    return config.external_is_mock("voice_api")


def recording_key(audio: bytes) -> str:
    return hashlib.sha256(audio).hexdigest()[:20]


def recording_path(audio: bytes) -> Path:
    return RECORDINGS / f"{recording_key(audio)}.json"


def local_audio(url: str | None) -> Path | None:
    """The file behind a media url this app serves. Anything else (empty, remote, outside the roots) is None."""
    if not url:
        return None
    for prefix, root in MEDIA_ROOTS:
        if url.startswith(prefix):
            base = root().resolve()
            path = (base / url[len(prefix):]).resolve()
            if base in path.parents and path.is_file():
                return path
    return None


def keyterms() -> list[str]:
    """Words the model should prefer: revision names and the project's units and sheets.

    On a noisy site note, "Rev A" came back as "Reb A" without them and right with them.
    """
    terms = [f"Rev {letter}" for letter in REVISION_LETTERS]
    project = store().get("project", "current") or {}
    for value in [*project.get("units", []), *project.get("sheets", [])]:
        term = str(value).strip()
        if term and len(term) <= 50 and len(term.split()) <= 5 and not KEYTERM_FORBIDDEN & set(term):
            terms.append(term)
    return list(dict.fromkeys(terms))[:MAX_KEYTERMS]


def _multipart(fields: list[tuple[str, str]], name: str, audio: bytes, media_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        for key, value in fields
    ]
    safe_name = name.replace('"', "").replace("\r", "").replace("\n", "") or "audio"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
        f"Content-Type: {media_type}\r\n\r\n"
    )
    parts.append(head.encode() + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _post(audio: bytes, name: str, media_type: str) -> dict:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise VoiceError("ELEVENLABS_API_KEY is not set")
    # Event tags like "(footsteps)" would end up in the record as if someone had said them.
    fields = [("model_id", MODEL_ID), ("tag_audio_events", "false"), *(("keyterms", t) for t in keyterms())]
    body, content_type = _multipart(fields, name, audio, media_type)
    request = urllib.request.Request(
        API, data=body, method="POST", headers={"xi-api-key": key, "Content-Type": content_type, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        message = f"speech to text refused with HTTP {error.code}"
        raise (_Retryable if error.code in RETRY_STATUS else VoiceError)(message) from None
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise _Retryable(f"speech to text unreachable: {type(reason).__name__}") from None
    except ValueError:
        raise VoiceError("speech to text answer is not JSON") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        raise VoiceError("speech to text answer has no text")
    return {"text": payload["text"], "language_code": payload.get("language_code")}


def call_service(audio: bytes, name: str, media_type: str) -> dict:
    """One real transcription with at most one retry. Raises VoiceError; refuses while the API is mocked."""
    if _mocked():
        raise RuntimeError("ElevenLabs call while USE_MOCK_VOICE_API is not false")
    started = time.monotonic()
    try:
        return _post(audio, name, media_type)
    except _Retryable as error:
        if time.monotonic() - started + TIMEOUT_SECONDS > DEADLINE_SECONDS:
            raise
        log.warning("voice: %s, retrying once", error)
        return _post(audio, name, media_type)


def _recorded(audio: bytes) -> str:
    path = recording_path(audio)
    if not path.is_file():
        raise VoiceError(f"no recorded answer {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))["answer"]["text"]
    except (ValueError, KeyError, TypeError):
        raise VoiceError(f"recorded answer {path.name} is unreadable") from None


def _text_for(event: m.InboundEvent, attachment: m.Attachment) -> str | None:
    path = local_audio(attachment.url)
    if path is None:
        # With the speech service mocked, an attachment without any file has nothing to send, so the mocked
        # service answers with the area mock's stand-in; against the live service it stays a failure.
        stand_in = mock.stand_in(event.id) if _mocked() and not attachment.url else None
        if stand_in:
            return stand_in
        raise VoiceError(f"audio file for {attachment.name} is not available")
    if path.stat().st_size > MAX_AUDIO_BYTES:
        raise VoiceError(f"audio file {attachment.name} is too large")
    audio = path.read_bytes()
    if _mocked():
        return _recorded(audio)
    media_type = attachment.media_type or "application/octet-stream"
    return call_service(audio, attachment.name, media_type)["text"]


def transcribe(event: m.InboundEvent) -> m.InboundEvent:
    """Fill `transcript` from the event's audio attachments. On failure the event comes back without one."""
    if event.transcript:
        return event
    texts = []
    for attachment in event.attachments:
        if attachment.kind != "audio":
            continue
        try:
            text = (_text_for(event, attachment) or "").strip()
        except VoiceError as error:
            log.warning("voice: no transcript for %s: %s", event.id, error)
            continue
        if text:
            texts.append(text)
    if not texts:
        return event
    return event.model_copy(update={"transcript": "\n".join(texts)})
