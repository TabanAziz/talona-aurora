"""The one way a message leaves the app: deliver(message) sends it through the channel area it names and stores
the outcome in the outbox. It never raises; every failure ends as a stored message with status failed and a
logged reason.

The stored message keeps `to` as the caller wrote it (a crew or person name). Real addresses from the directory
are only put on the copy handed to the channel, so they never reach the outbox, the record or the API.
"""
import logging
import threading

from app.core import config, models as m
from app.core import registry
from app.core.store import store
from app.language import localize, localize_reply

from . import directory

log = logging.getLogger(__name__)

SENDING_CHANNELS = ("telegram", "email", "whatsapp")
MACHINE_CHANNEL = "machine"
DONE = ("sent", "simulated")

_lock = threading.Lock()
_in_flight: set[tuple[str, str]] = set()


class DeliveryError(Exception):
    """A reason the message cannot be sent. Its text names no address."""


def _recipient(message: m.OutboundMessage) -> str:
    to = message.to.strip()
    if not to:
        raise DeliveryError("message has no recipient")
    if message.channel == "telegram":
        # The Telegram channel posts to the group chat or replies in the original chat; `to` is the label.
        return to
    if message.channel == "email" and "@" in to:
        return to
    if message.channel == "whatsapp" and (to.startswith("whatsapp:") or to.startswith("+")):
        return to
    handles = directory.reach(to, message.channel)
    if not handles:
        raise DeliveryError(f"no {message.channel} address for {to!r} in the directory")
    return ", ".join(handles) if message.channel == "email" else handles[0]


def _earlier_text(event_id: str | None) -> str:
    if not event_id:
        return ""
    event = store().get("events", event_id) or {}
    return (event.get("transcript") or event.get("text") or "").strip()


def _localized(message: m.OutboundMessage) -> m.OutboundMessage:
    """The copy the reader gets: in the language of the event it answers, else in the language stored for the
    recipient, else English. Only this copy is translated; the outbox keeps the English text."""
    try:
        earlier = _earlier_text(message.in_reply_to)
        if earlier:
            return localize_reply(message, earlier)
        return localize(message, directory.language(message.to, message.channel))
    except Exception as error:
        log.error("delivery: %s not localized, sent in English: %s", message.id, type(error).__name__)
        return message


def _outgoing(message: m.OutboundMessage) -> m.OutboundMessage:
    # A machine is addressed by the name it fetches with and reads no language, so its notice goes as written.
    if message.channel == MACHINE_CHANNEL:
        return message
    return _localized(message).model_copy(update={"to": _recipient(message)})


def _send(message: m.OutboundMessage) -> m.OutboundMessage:
    if message.channel not in SENDING_CHANNELS and message.channel != MACHINE_CHANNEL:
        raise DeliveryError(f"channel {message.channel!r} cannot send")
    if message.channel in SENDING_CHANNELS:
        from app.workspace.channels import allowed
        if not allowed(message.channel):
            if config.external_is_mock(f"{message.channel}_api"):
                return message.model_copy(update={"status": "simulated"})
            raise DeliveryError("This messaging account is not enabled for this project")
    outgoing = _outgoing(message)
    try:
        result = registry.area(message.channel).send(outgoing)
    except Exception as error:
        # Only the type: a channel's error text can carry an address or a token.
        raise DeliveryError(f"{message.channel} send raised {type(error).__name__}") from None
    status = getattr(result, "status", None)
    if status not in ("sent", "simulated", "failed"):
        raise DeliveryError(f"{message.channel} send returned status {status!r}")
    if status == "failed":
        raise DeliveryError(f"{message.channel} channel reported the send as failed")
    return message.model_copy(update={"status": status})


def _keep(message: m.OutboundMessage) -> None:
    try:
        store().put("outbox", message.id, message)
    except Exception as error:
        log.error("delivery: outbox entry %s not stored: %s", message.id, type(error).__name__)


def _already_done(message_id: str) -> m.OutboundMessage | None:
    try:
        existing = store().get("outbox", message_id)
        if existing and existing.get("status") in DONE:
            return m.OutboundMessage.model_validate(existing)
    except Exception as error:
        log.error("delivery: outbox lookup for %s failed: %s", message_id, type(error).__name__)
    return None


def deliver(message: m.OutboundMessage) -> m.OutboundMessage:
    """Send once, store the outcome, return the stored message. A message already sent or simulated is returned as
    stored without sending again; a failed one is tried again."""
    with _lock:
        done = _already_done(message.id)
        if done is not None:
            return done
        sending_key = (str(config.data_dir().resolve()), message.id)
        if sending_key in _in_flight:
            log.info("delivery: %s is being sent by another caller, not sent twice", message.id)
            return message
        _in_flight.add(sending_key)
    try:
        try:
            outcome = _send(message)
        except DeliveryError as error:
            log.warning("delivery: %s via %s failed: %s", message.id, message.channel, error)
            outcome = message.model_copy(update={"status": "failed"})
        except Exception as error:
            log.error("delivery: %s via %s failed unexpectedly: %s", message.id, message.channel, type(error).__name__)
            outcome = message.model_copy(update={"status": "failed"})
        # Stored before the id is released, so a concurrent caller sees the outcome instead of sending again.
        _keep(outcome)
    finally:
        with _lock:
            _in_flight.discard(sending_key)
    return outcome
