"""Telegram channel: Bot API webhook updates in, text, images and buttons out.

Every network call goes through `_api` or `_download`, and both refuse to run while
`USE_MOCK_TELEGRAM_API` is unset or true. In that mode voice files come from `fixtures/files`
and `send` only marks the message as simulated.
"""
import json
import logging
import mimetypes
import os
import re
import shutil
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core import config
from app.core import models as m
from app.core.store import store
from app.core.registry import area

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT_SECONDS = 10
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
CAPTION_LIMIT = 1024
FIXTURE_FILES = Path(__file__).parent / "fixtures" / "files"
PHOTO_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
# Telegram plays these as a voice message the crew can tap, instead of a file to download.
SPEAKABLE_SUFFIXES = {".mp3", ".ogg", ".m4a", ".wav"}
AUDIO_SUFFIXES = {"audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
                  "audio/x-m4a": ".m4a", "audio/wav": ".wav"}
EVENT_ID = re.compile(r"^tg-(-?\d+)-(\d+)")


class TelegramError(Exception):
    pass


def _mocked() -> bool:
    return config.external_is_mock("telegram_api")


def _token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    return token


def _open(request: urllib.request.Request) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read(MAX_DOWNLOAD_BYTES + 1)
    except urllib.error.HTTPError as error:
        # The Bot API explains a refusal in the JSON body; the URL holds the token and is never logged.
        try:
            detail = json.loads(error.read()).get("description", "")
        except ValueError:
            detail = ""
        raise TelegramError(f"HTTP {error.code} {detail}".strip()) from None
    except OSError as error:
        reason = getattr(error, "reason", error)
        raise TelegramError(f"network error: {type(reason).__name__}") from None


def _multipart(fields: dict, files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        text = value if isinstance(value, str) else json.dumps(value)
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{text}\r\n'.encode())
    for name, path in files.items():
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
            f"Content-Type: {media_type}\r\n\r\n"
        )
        parts.append(head.encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _api(method: str, fields: dict, files: dict[str, Path] | None = None) -> dict:
    """One Bot API call. Returns `result`, raises TelegramError on any refusal or network failure."""
    if _mocked():
        raise RuntimeError(f"Telegram API call {method} while USE_MOCK_TELEGRAM_API is not false")
    url = f"{API}/bot{_token()}/{method}"
    if files:
        body, content_type = _multipart(fields, files)
    else:
        body, content_type = json.dumps(fields).encode(), "application/json"
    raw = _open(urllib.request.Request(url, data=body, headers={"Content-Type": content_type}, method="POST"))
    try:
        reply = json.loads(raw)
    except ValueError:
        raise TelegramError(f"{method}: answer is not JSON") from None
    if not reply.get("ok"):
        raise TelegramError(f"{method}: {reply.get('description', 'refused')}")
    return reply.get("result") or {}


def _download(file_path: str) -> bytes:
    if _mocked():
        raise RuntimeError("Telegram file download while USE_MOCK_TELEGRAM_API is not false")
    raw = _open(urllib.request.Request(f"{API}/file/bot{_token()}/{file_path}", method="GET"))
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise TelegramError("file is larger than the Bot API download limit")
    return raw


def _sender(user: dict) -> str:
    name = " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part)
    return name or user.get("username") or str(user.get("id", "unknown"))


def _at(unix: int | None) -> datetime:
    return datetime.fromtimestamp(unix, timezone.utc) if unix else datetime.now(timezone.utc)


def _stored_file(media: dict, default_name: str, kind: str, suffix: str,
                 media_type: str) -> m.Attachment:
    """Store the file under DATA_DIR/files/telegram. A failed download keeps the attachment without a url."""
    unique = re.sub(r"[^A-Za-z0-9_-]", "", media.get("file_unique_id") or media.get("file_id") or uuid.uuid4().hex)
    name = media.get("file_name") or f"{default_name}{suffix}"
    target_dir = config.data_dir() / "files" / "telegram"
    target = target_dir / f"{unique}{suffix}"
    url = f"/media/files/telegram/{target.name}"
    try:
        if _mocked():
            fixture = FIXTURE_FILES / f"{unique}{suffix}"
            if not fixture.is_file():
                return m.Attachment(kind=kind, name=name, url=None, media_type=media_type)
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fixture, target)
        else:
            if (media.get("file_size") or 0) > MAX_DOWNLOAD_BYTES:
                raise TelegramError("file is larger than the Bot API download limit")
            info = _api("getFile", {"file_id": media["file_id"]})
            data = _download(info["file_path"])
            target_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    except (TelegramError, KeyError) as error:
        log.warning("telegram: %s download failed: %s", kind, error)
        url = None
    return m.Attachment(kind=kind, name=name, url=url, media_type=media_type)


def _voice_attachment(media: dict, default_name: str) -> m.Attachment:
    """Store the audio under DATA_DIR/files/telegram. A failed download keeps the attachment without a url."""
    media_type = media.get("mime_type") or "audio/ogg"
    suffix = AUDIO_SUFFIXES.get(media_type) or Path(media.get("file_name") or default_name).suffix or ".ogg"
    return _stored_file(media, default_name, "audio", suffix, media_type)


def _photo_attachment(message: dict) -> m.Attachment | None:
    """The largest size of a photo message, downloaded as a JPEG the title block read can decode."""
    sizes = [item for item in message.get("photo") or [] if isinstance(item, dict) and item.get("file_id")]
    if not sizes:
        return None
    best = max(sizes, key=lambda item: item.get("file_size") or 0)
    return _stored_file(best, "photo", "image", ".jpg", "image/jpeg")


def _from_message(message: dict) -> m.InboundEvent | None:
    user = message.get("from") or {}
    if user.get("is_bot"):
        return None
    text = message.get("text") or message.get("caption") or ""
    attachments: list[m.Attachment] = []
    if message.get("voice"):
        attachments.append(_voice_attachment(message["voice"], "voice-note"))
    elif message.get("audio"):
        attachments.append(_voice_attachment(message["audio"], "audio"))
    elif message.get("photo"):
        photo = _photo_attachment(message)
        if photo is not None:
            attachments.append(photo)
    if not text and not attachments:
        return None
    chat = message.get("chat") or {}
    return m.InboundEvent(
        id=f"tg-{chat.get('id')}-{message.get('message_id')}",
        channel="telegram",
        sent_at=_at(message.get("date")),
        received_at=datetime.now(timezone.utc),
        sender=_sender(user),
        thread=chat.get("title"),
        text=text,
        attachments=attachments,
    )


def _button_label(query: dict) -> str:
    data = query.get("data") or ""
    keyboard = ((query.get("message") or {}).get("reply_markup") or {}).get("inline_keyboard") or []
    for row in keyboard:
        for button in row:
            if button.get("callback_data") == data:
                return button.get("text") or data
    return data


def _from_button(query: dict) -> m.InboundEvent | None:
    label = _button_label(query)
    if not label:
        return None
    message = query.get("message") or {}
    chat = message.get("chat") or {}
    if not _mocked():
        try:
            _api("answerCallbackQuery", {"callback_query_id": query["id"]})
        except TelegramError as error:
            # The press is already recorded; a missed acknowledgement only leaves the button spinning.
            log.warning("telegram: answerCallbackQuery failed: %s", error)
    now = datetime.now(timezone.utc)
    return m.InboundEvent(
        id=f"tg-{chat.get('id')}-{message.get('message_id')}-cb{query.get('id')}",
        channel="telegram",
        sent_at=now,
        received_at=now,
        sender=_sender(query.get("from") or {}),
        thread=chat.get("title"),
        subject=message.get("text") or message.get("caption"),
        text=label,
    )


def _guest_reply(chat: str, text: str, buttons=()) -> None:
    if _mocked():
        return
    fields = {"chat_id": chat, "text": text}
    if buttons:
        fields["reply_markup"] = {"inline_keyboard": [[{"text": label, "callback_data": data}]
                                                       for label, data in buttons]}
    try:
        _api("sendMessage", fields)
    except TelegramError:
        log.warning("telegram: guest onboarding reply failed")


def parse(update: dict) -> list[m.InboundEvent]:
    """One webhook update becomes at most one event. Updates Aurora does not read give an empty list."""
    guest_events = area("guest").intercept(update, _from_message, _from_button, _guest_reply)
    if guest_events is not None:
        query = update.get("callback_query")
        if not guest_events and query and query.get("id") and not _mocked():
            try:
                _api("answerCallbackQuery", {"callback_query_id": query["id"]})
            except TelegramError:
                log.warning("telegram: guest button acknowledgement failed")
        return guest_events
    if update.get("message"):
        event = _from_message(update["message"])
    elif update.get("callback_query"):
        event = _from_button(update["callback_query"])
    else:
        event = None
    return [event] if event else []


def _default_chat() -> str | None:
    configured = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if configured:
        return configured
    # Without a configured group, answer in the chat Aurora heard from last.
    for event in reversed(store().list("events")):
        match = EVENT_ID.match(event.get("id", ""))
        if event.get("channel") == "telegram" and match:
            return match.group(1)
    return None


def _target(message: m.OutboundMessage) -> tuple[str, int | None]:
    from app.workspace.channels import binding, group_chat
    if binding("telegram"):
        chat = group_chat()
        if not chat:
            raise TelegramError("the configured group is not enabled for this project")
        match = EVENT_ID.match(message.in_reply_to or "")
        return chat, int(match.group(2)) if match and match.group(1) == chat else None
    try:
        guest = area("guest").target(message)
    except ValueError:
        raise TelegramError("guest private route is unavailable") from None
    if guest is not None:
        return guest
    match = EVENT_ID.match(message.in_reply_to or "")
    if match:
        return match.group(1), int(match.group(2))
    chat = _default_chat()
    if chat is None:
        raise TelegramError("no chat to send to: set TELEGRAM_CHAT_ID or let the group write first")
    return chat, None


def _reply(message_id: int) -> dict:
    # A deleted original must not cost the crew the answer.
    return {"message_id": message_id, "allow_sending_without_reply": True}


def _local_media(url: str) -> Path | None:
    for prefix, base in (("/media/mock/", config.ROOT / "mocks" / "assets"), ("/media/files/", config.data_dir() / "files")):
        if url.startswith(prefix):
            path = (base / url[len(prefix):]).resolve()
            if base.resolve() in path.parents and path.is_file():
                return path
    return None


def _send_media(chat: str, reply_to: int | None, url: str, caption: str | None, markup: dict | None) -> None:
    fields: dict = {"chat_id": chat}
    if reply_to:
        fields["reply_parameters"] = _reply(reply_to)
    if caption:
        fields["caption"] = caption
    if markup:
        fields["reply_markup"] = markup
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    if suffix in PHOTO_SUFFIXES:
        method, field = "sendPhoto", "photo"
    elif suffix in SPEAKABLE_SUFFIXES:
        # A spoken briefing is meant to be played in the chat, not downloaded as an attachment.
        method, field = "sendVoice", "voice"
    else:
        method, field = "sendDocument", "document"
    if url.startswith(("http://", "https://")):
        _api(method, {**fields, field: url})
        return
    path = _local_media(url)
    if path is None:
        raise TelegramError(f"media {url} not found")
    _api(method, fields, files={field: path})


def send(message: m.OutboundMessage) -> m.OutboundMessage:
    if _mocked():
        return message.model_copy(update={"status": "simulated"})
    from app.workspace.channels import allowed
    if not allowed("telegram"):
        return message.model_copy(update={"status": "failed"})
    try:
        chat, reply_to = _target(message)
        text = message.text if reply_to else f"{message.to}: {message.text}"
        markup = None
        if message.buttons:
            # The press comes back with this data; parse turns it into the label from the keyboard.
            markup = {"inline_keyboard": [
                [{"text": label, "callback_data": f"{i}:{message.id}"[:64]}] for i, label in enumerate(message.buttons)
            ]}
        if message.media_url and len(text) <= CAPTION_LIMIT:
            _send_media(chat, reply_to, message.media_url, text, markup)
        else:
            if message.media_url:
                _send_media(chat, reply_to, message.media_url, None, None)
            fields: dict = {"chat_id": chat, "text": text}
            if reply_to:
                fields["reply_parameters"] = _reply(reply_to)
            if markup:
                fields["reply_markup"] = markup
            _api("sendMessage", fields)
    except TelegramError as error:
        log.warning("telegram: send %s failed: %s", message.id, error)
        return message.model_copy(update={"status": "failed"})
    return message.model_copy(update={"status": "sent"})
