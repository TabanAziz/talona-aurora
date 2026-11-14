"""WhatsApp channel through Twilio: webhook forms in, messages out. One-to-one chats only, Twilio has no groups.

Every network call refuses to run unless USE_MOCK_WHATSAPP_API=false. Mocked, `parse` still reads forms (no
media download) and `send` only marks the message as simulated.
"""
import base64
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from app.core import config
from app.core import models as m

log = logging.getLogger(__name__)

API = "https://api.twilio.com/2010-04-01"
TIMEOUT_S = 15
SEND_ATTEMPTS = 2
MAX_MEDIA_BYTES = 15 * 1024 * 1024
MAX_MEDIA = 3
BODY_LIMIT = 1500
EXTENSIONS = {
    "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/amr": ".amr",
    "image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf",
}


def _mocked() -> bool:
    return config.external_is_mock("whatsapp_api")


def _credentials() -> tuple[str, str]:
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    if not sid or not token:
        raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set to use WhatsApp")
    return sid, token


def _auth_header(sid: str, token: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode()}


def _number(value: str) -> str:
    return re.sub(r"\s", "", value.strip()).removeprefix("whatsapp:")


def _kind(media_type: str) -> str:
    if media_type == "application/pdf":
        return "pdf"
    major = media_type.split("/", 1)[0]
    return major if major in ("audio", "image") else "file"


def _download(url: str, event_id: str, index: int, media_type: str) -> str | None:
    """Twilio media needs the account login. The file lands in DATA_DIR/files and is served from there."""
    if not url.startswith("https://api.twilio.com/"):
        return None
    sid, token = _credentials()
    request = urllib.request.Request(url, headers=_auth_header(sid, token))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            data = response.read(MAX_MEDIA_BYTES + 1)
    except (urllib.error.URLError, OSError) as error:
        log.warning("whatsapp media %s of %s not downloaded: %s", index, event_id, type(error).__name__)
        return None
    if not data or len(data) > MAX_MEDIA_BYTES:
        return None
    name = f"media-{index}{EXTENSIONS.get(media_type, '.bin')}"
    folder = config.data_dir() / "files" / event_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return f"/media/files/{event_id}/{name}"


def parse(form: dict) -> list[m.InboundEvent]:
    """A Twilio webhook form becomes one event. Forms from another account, without a sender or without
    content are dropped."""
    if not _mocked():
        sid, _ = _credentials()
        if form.get("AccountSid") != sid:
            log.warning("whatsapp form dropped: it does not come from the configured account")
            return []
    message_sid = str(form.get("MessageSid") or form.get("SmsMessageSid") or "").strip()
    sender_number = _number(str(form.get("From") or ""))
    if not message_sid or not sender_number:
        return []

    event_id = f"wa-{message_sid}"
    attachments = []
    try:
        media_count = min(int(form.get("NumMedia") or 0), MAX_MEDIA)
    except ValueError:
        media_count = 0
    for index in range(media_count):
        media_type = str(form.get(f"MediaContentType{index}") or "application/octet-stream")
        url = str(form.get(f"MediaUrl{index}") or "")
        saved = None if _mocked() or not url else _download(url, event_id, index, media_type)
        attachments.append(m.Attachment(
            kind=_kind(media_type), name=f"media-{index}{EXTENSIONS.get(media_type, '.bin')}", url=saved,
            media_type=media_type,
        ))
    body = str(form.get("Body") or form.get("ButtonText") or "").strip()[:BODY_LIMIT]
    if not body and not attachments:
        return []

    now = datetime.now(timezone.utc)
    return [m.InboundEvent(
        id=event_id, channel="whatsapp", sent_at=now, received_at=now,
        sender=str(form.get("ProfileName") or "").strip() or sender_number, text=body, attachments=attachments,
    )]


def _from_number() -> str:
    number = _number(os.environ.get("TWILIO_WHATSAPP_FROM", ""))
    if not number:
        raise RuntimeError("TWILIO_WHATSAPP_FROM must be set to send WhatsApp messages")
    return number


def send(message: m.OutboundMessage) -> m.OutboundMessage:
    if _mocked():
        return message.model_copy(update={"status": "simulated"})
    target = _number(message.to)
    if not re.fullmatch(r"\+\d{7,15}", target):
        log.warning("message %s not sent: the recipient is not an international number", message.id)
        return message.model_copy(update={"status": "failed"})
    sid, token = _credentials()
    text = message.text
    if message.buttons:
        text += "\n\nReply with one of: " + ", ".join(message.buttons)
    fields = {"From": f"whatsapp:{_from_number()}", "To": f"whatsapp:{target}", "Body": text[:BODY_LIMIT]}
    if message.media_url and message.media_url.startswith("https://"):
        fields["MediaUrl"] = message.media_url
    request = urllib.request.Request(
        f"{API}/Accounts/{urllib.parse.quote(sid)}/Messages.json",
        data=urllib.parse.urlencode(fields).encode(),
        headers=_auth_header(sid, token), method="POST",
    )
    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S):
                return message.model_copy(update={"status": "sent"})
        except urllib.error.HTTPError as error:
            log.warning("whatsapp send %s refused: HTTP %s", message.id, error.code)
            if error.code < 500:
                break
        except OSError as error:
            log.warning("whatsapp send %s failed (attempt %d): %s", message.id, attempt, type(error).__name__)
    return message.model_copy(update={"status": "failed"})
