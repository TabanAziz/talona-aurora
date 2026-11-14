"""Email channel: reads the project mailbox over IMAP and sends mail over SMTP.

Only the deployed app talks to the live mailbox. Unless USE_MOCK_EMAIL_API=false, poll returns
nothing and send marks the message as simulated, so no test or e2e run touches a network.
"""
import hashlib
import imaplib
import logging
import mimetypes
import os
import re
import smtplib
import threading
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage, Message
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from app.core import config, pipeline
from app.core import models as m

log = logging.getLogger(__name__)

TIMEOUT_S = 20
MAX_PER_POLL = 25
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 20000
SEND_ATTEMPTS = 2
IMAP_PORT = 993
SMTP_PORT = 465
UNKNOWN_SENDER = "Unknown sender"
# With the mailbox loop polling every 20 s a mail that keeps failing gets about a minute and a half of tries.
MAX_OFFERS = 5

_offers: dict[str, int] = {}
# Mail given up on is not fetched again, so a large attachment is not downloaded on every poll.
_given_up_uids: set[bytes] = set()
_offers_lock = threading.Lock()


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextOnly()
    parser.feed(html)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def _credentials() -> tuple[str, str]:
    address = os.environ.get("EMAIL_ADDRESS", "").strip()
    password = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    if not address or not password:
        raise RuntimeError("EMAIL_ADDRESS and EMAIL_APP_PASSWORD must be set to use the live mailbox")
    return address, password


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _header_date(message: Message) -> datetime | None:
    try:
        return _utc(parsedate_to_datetime(str(message["Date"])))
    except (TypeError, ValueError):
        return None


def _received_date(message: Message) -> datetime | None:
    """The mail server stamps the newest Received header first; its date follows the last semicolon."""
    first = message.get("Received")
    if not first:
        return None
    try:
        return _utc(parsedate_to_datetime(str(first).rsplit(";", 1)[1].strip()))
    except (IndexError, TypeError, ValueError):
        return None


def _event_id(message: Message, raw: bytes) -> str:
    """Stable per mail: a redelivered message keeps its Message-ID and so its id, and the pipeline drops it."""
    key = str(message["Message-ID"] or "").strip() or hashlib.sha1(raw).hexdigest()
    return "mail-" + hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:12]


def _sender(message: Message) -> str:
    try:
        address = message["From"].addresses[0]
    except (AttributeError, IndexError):
        return UNKNOWN_SENDER
    return address.display_name or address.addr_spec or UNKNOWN_SENDER


def _thread(message: Message) -> str | None:
    if not (message["In-Reply-To"] or message["References"]):
        return None
    subject = re.sub(r"^((re|fw|fwd)\s*:\s*)+", "", str(message["Subject"] or ""), flags=re.IGNORECASE).strip()
    return subject or None


def _body(message: Message) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except (LookupError, UnicodeError):
        return ""
    if part.get_content_type() == "text/html":
        text = _html_to_text(text)
    return text.strip()[:MAX_TEXT_CHARS]


def _kind(media_type: str) -> str:
    if media_type == "application/pdf":
        return "pdf"
    major = media_type.split("/", 1)[0]
    return major if major in ("image", "audio") else "file"


def _safe_name(name: str | None, index: int) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]", "_", Path((name or "").replace("\\", "/")).name).lstrip(".")
    return base or f"attachment-{index}"


def _save_attachments(message: Message, event_id: str) -> list[m.Attachment]:
    attachments = []
    folder = config.data_dir() / "files" / event_id
    used: set[str] = set()
    for index, part in enumerate(message.iter_attachments(), start=1):
        name = _safe_name(part.get_filename(), index)
        if name in used:
            name = f"{index}-{name}"
        used.add(name)
        media_type = part.get_content_type()
        payload = part.get_payload(decode=True) or b""
        url = None
        if 0 < len(payload) <= MAX_ATTACHMENT_BYTES:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(payload)
            url = f"/media/files/{event_id}/{name}"
        else:
            log.warning("attachment %s of %s not saved: %d bytes", name, event_id, len(payload))
        attachments.append(m.Attachment(kind=_kind(media_type), name=name, url=url, media_type=media_type))
    return attachments


def parse_message(raw: bytes, received_at: datetime | None = None) -> m.InboundEvent:
    """One raw mail becomes one event. Attachments are saved under DATA_DIR/files/<event id>/."""
    message = message_from_bytes(raw, policy=policy.default)
    event_id = _event_id(message, raw)
    received = _received_date(message) or received_at or datetime.now(timezone.utc)
    sent = _header_date(message) or received
    return m.InboundEvent(
        id=event_id,
        channel="email",
        sent_at=sent,
        received_at=max(received, sent),
        sender=_sender(message),
        thread=_thread(message),
        subject=str(message["Subject"]) if message["Subject"] else None,
        text=_body(message),
        attachments=_save_attachments(message, event_id),
    )


def _is_from(raw: bytes, address: str) -> bool:
    """Our own replies can land in the inbox; they must not become events."""
    header = message_from_bytes(raw, policy=policy.default)["From"]
    try:
        return any(a.addr_spec.lower() == address.lower() for a in header.addresses)
    except AttributeError:
        return False


def _imap() -> imaplib.IMAP4_SSL:
    address, password = _credentials()
    conn = imaplib.IMAP4_SSL(os.environ.get("EMAIL_IMAP_HOST") or "imap.gmail.com", IMAP_PORT, timeout=TIMEOUT_S)
    conn.login(address, password)
    return conn


def _fetch(conn: imaplib.IMAP4_SSL, uid: bytes) -> bytes | None:
    status, data = conn.uid("fetch", uid, "(BODY.PEEK[])")
    if status != "OK":
        return None
    for item in data:
        if isinstance(item, tuple) and isinstance(item[1], bytes):
            return item[1]
    return None


def forget_attempts() -> None:
    """Offer every unseen mail again, also the ones given up on."""
    with _offers_lock:
        _offers.clear()
        _given_up_uids.clear()


def _offer(event_id: str) -> bool:
    """Count one more offer of a mail that is not ingested yet; False once it has had all its tries."""
    with _offers_lock:
        count = _offers.get(event_id, 0)
        if count >= MAX_OFFERS:
            return False
        _offers[event_id] = count + 1
    if count + 1 == MAX_OFFERS:
        log.warning("mail %s offered %d times without being ingested; after this try it is left unseen and "
                    "not offered again until the app restarts", event_id, MAX_OFFERS)
    elif count:
        log.info("mail %s offered again (try %d of %d)", event_id, count + 1, MAX_OFFERS)
    return True


def poll() -> list[m.InboundEvent]:
    """Unseen mail in the inbox as events, oldest first.

    A mail is marked seen only on the poll after the pipeline ingested it, so a mail whose ingest raised stays
    unseen and is offered again. The contract gives poll no callback, so the store is what says it was ingested.
    """
    if config.external_is_mock("email_api"):
        return []
    own_address, _ = _credentials()
    events: list[m.InboundEvent] = []
    conn = _imap()
    try:
        status, _ = conn.select("INBOX")
        if status != "OK":
            raise RuntimeError("the mailbox INBOX could not be opened")
        from app.workspace.channels import binding
        target = binding("email") if config.project_directory.get() is not None else None
        if target and target.get("updated_at"):
            since = datetime.fromisoformat(target["updated_at"]).strftime("%d-%b-%Y")
            status, found = conn.uid("search", None, "SINCE", since)
        else:
            status, found = conn.uid("search", None, "UNSEEN")
        uids = found[0].split() if status == "OK" and found and found[0] else []
        for uid in uids:
            if len(events) >= MAX_PER_POLL:
                break
            if uid in _given_up_uids:
                continue
            raw = _fetch(conn, uid)
            if raw is None:
                log.warning("mail uid %s could not be fetched, it stays unseen", uid.decode())
                continue
            if config.project_directory.get() is not None and target and target.get("updated_at"):
                message = message_from_bytes(raw, policy=policy.default)
                received = _received_date(message) or _header_date(message)
                if received is not None and received < datetime.fromisoformat(target["updated_at"]):
                    continue
            if _is_from(raw, own_address):
                conn.uid("store", uid, "+FLAGS", "(\\Seen)")
                continue
            event_id = _event_id(message_from_bytes(raw, policy=policy.default), raw)
            if pipeline.is_ingested(event_id):
                conn.uid("store", uid, "+FLAGS", "(\\Seen)")
                with _offers_lock:
                    _offers.pop(event_id, None)
                continue
            if _offer(event_id):
                events.append(parse_message(raw))
            else:
                with _offers_lock:
                    _given_up_uids.add(uid)
    finally:
        try:
            conn.logout()
        except (imaplib.IMAP4.error, OSError):
            log.debug("imap logout failed")
    return events


def _compose(message: m.OutboundMessage, sender: str) -> EmailMessage:
    mail = EmailMessage()
    mail["From"] = sender
    mail["To"] = message.to
    from app.core.store import store
    project_name = (store().get("project", "current") or {}).get("name", "Aurora")
    mail["Subject"] = f"{project_name}: {message.reason}"[:120]
    body = message.text
    if message.buttons:
        body += "\n\nPlease reply with one of: " + ", ".join(message.buttons)
    mail.set_content(body)
    if message.media_url and message.media_url.startswith("/media/files/"):
        path = (config.data_dir() / "files" / message.media_url.removeprefix("/media/files/")).resolve()
        if path.is_file() and (config.data_dir() / "files").resolve() in path.parents:
            guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            major, _, minor = guessed.partition("/")
            mail.add_attachment(path.read_bytes(), maintype=major, subtype=minor, filename=path.name)
    return mail


def send(message: m.OutboundMessage) -> m.OutboundMessage:
    if config.external_is_mock("email_api"):
        return message.model_copy(update={"status": "simulated"})
    from app.workspace.channels import allowed
    if not allowed("email"):
        return message.model_copy(update={"status": "failed"})
    if "@" not in message.to:
        log.warning("message %s not sent: %r is not an email address", message.id, message.to)
        return message.model_copy(update={"status": "failed"})
    address, password = _credentials()
    mail = _compose(message, address)
    host = os.environ.get("EMAIL_SMTP_HOST") or "smtp.gmail.com"
    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            with smtplib.SMTP_SSL(host, SMTP_PORT, timeout=TIMEOUT_S) as smtp:
                smtp.login(address, password)
                smtp.send_message(mail)
            return message.model_copy(update={"status": "sent"})
        except (smtplib.SMTPException, OSError) as error:
            log.warning("sending %s failed (attempt %d): %s", message.id, attempt, type(error).__name__)
    return message.model_copy(update={"status": "failed"})
