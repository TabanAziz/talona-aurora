"""Private demo guests. Handles, quotas and message routes stay in the runtime store."""
import copy
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from app.core import config, models as m
from app.core.store import store
from app.live import directory

MAX_GUESTS = 10
MAX_MESSAGES = 5
WINDOW_SECONDS = 600
MAX_TEXT = 500
MAX_AUDIO_SECONDS = 30
ROLES = {"framing": ("Framing foreman", "Framing crew"), "drywall": ("Drywall foreman", "Drywall crew")}
BUTTONS = [(role, f"guest:{key}") for key, (role, _) in ROLES.items()]
WELCOME = (
    "Welcome to Aurora. This is a demo site with synthetic data. Choose your role below. "
    "Try a text or voice note:\n"
    "1. Starting 3B tomorrow per Rev B.\n"
    "2. Can we close the wall in 3B?\n"
    "3. The lumber delivery is two days late."
)
_lock = threading.RLock()
_cause: ContextVar[str | None] = ContextVar("guest_delivery_cause", default=None)


def _now() -> float:
    return time.time()


def _limit() -> int:
    try:
        return min(MAX_GUESTS, max(0, int(os.environ.get("GUEST_LIMIT", str(MAX_GUESTS)))))
    except ValueError:
        return MAX_GUESTS


def _guest(user: str) -> dict | None:
    return next((g for g in store().list("guests") if g["user"] == user), None)


def _save(guest: dict) -> None:
    store().put("guests", guest["id"], guest)


def _first_name(user: dict) -> str:
    # Keep only the requested display name, never a username, surname or numeric fallback.
    return " ".join(str(user.get("first_name") or "Visitor").split())[:80] or "Visitor"


def intercept(update: dict, parse_message, parse_button, reply) -> list[m.InboundEvent] | None:
    """None leaves a known sender or group to the ordinary Telegram parser; a list consumes the update."""
    with _lock:
        return _intercept(update, parse_message, parse_button, reply)


def mutation_scope():
    return _lock


def _intercept(update: dict, parse_message, parse_button, reply) -> list[m.InboundEvent] | None:
    query = update.get("callback_query")
    message = (query or {}).get("message") or update.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return None
    user = (query or {}).get("from") or message.get("from") or {}
    if user.get("is_bot"):
        return []
    user_id, chat_id = str(user.get("id") or ""), str(chat.get("id") or "")
    if not re.fullmatch(r"[1-9][0-9]*", user_id) or user_id != chat_id:
        return []
    joined = (message.get("text") or "").strip().split()
    join_attempt = not query and len(joined) == 2 and joined[0].split("@", 1)[0] == "/start" and joined[1] == "guest"
    guest = _guest(user_id)
    if directory.resolve("telegram", user_id).known and guest is None:
        return None
    enabled = config.flag("GUEST_MODE") is True
    if not enabled:
        if join_attempt or (query and str(query.get("data", "")).startswith("guest:")):
            reply(chat_id, "Guest mode is disabled for this demo.")
            return []
        # A guest who joined earlier must not fall back to the normal site channel after disabling the mode.
        return [] if guest else None
    if join_attempt:
        if guest is None:
            if len(store().list("guests")) >= _limit():
                reply(chat_id, "The demo guest list is full. Please try again after the next reset.")
                return []
            guest = {"id": uuid.uuid4().hex, "user": user_id, "chat": chat_id,
                     "name": _first_name(user), "role": None, "accepted": []}
            _save(guest)
        reply(chat_id, WELCOME, BUTTONS)
        return []
    if guest is None:
        reply(chat_id, "To join this synthetic demo site, open the bot link with start=guest or send /start guest.")
        return []
    selection = str((query or {}).get("data") or "").removeprefix("guest:")
    if query and str(query.get("data") or "").startswith("guest:"):
        if selection not in ROLES:
            reply(chat_id, "Choose Framing foreman or Drywall foreman below.", BUTTONS)
            return []
        guest["role"] = selection
        _save(guest)
        reply(chat_id, f"You are the {ROLES[selection][0].lower()} on this synthetic demo site. Send a text or voice note.")
        return []
    if guest["role"] not in ROLES:
        reply(chat_id, "Choose your demo role first.", BUTTONS)
        return []
    text = "" if query else message.get("text") or message.get("caption") or ""
    media = None if query else message.get("voice") or message.get("audio")
    if len(text) > MAX_TEXT:
        reply(chat_id, "Please keep demo messages to 500 characters or fewer.")
        return []
    if media:
        duration = media.get("duration")
        if not isinstance(duration, (int, float)) or duration < 0 or duration > MAX_AUDIO_SECONDS:
            reply(chat_id, "Please send a voice note of 30 seconds or less.")
            return []
    if not query and not text and not media:
        reply(chat_id, "Please send a text or voice note for this demo.")
        return []
    key = f"callback:{query.get('id')}" if query else f"message:{message.get('message_id')}"
    route = next((r for r in store().list("guest_routes") if r["guest"] == guest["id"] and r["key"] == key), None)
    if route is None:
        now = _now()
        guest["accepted"] = [stamp for stamp in guest["accepted"] if now - stamp < WINDOW_SECONDS]
        if len(guest["accepted"]) >= MAX_MESSAGES:
            reply(chat_id, "The demo allows 5 messages in 10 minutes. Please wait before trying again.")
            return []
        route = {"id": f"guest-{uuid.uuid4().hex}", "guest": guest["id"], "key": key,
                 "message": message.get("message_id"), "media": uuid.uuid4().hex}
        store().put("guest_routes", route["id"], route)
        guest["accepted"].append(now)
        _save(guest)
    safe = copy.deepcopy(message)
    for kind in ("voice", "audio"):
        if safe.get(kind):
            safe[kind]["file_unique_id"] = route["media"]
            safe[kind]["file_name"] = "guest-voice-note.ogg"
    event = parse_button(query) if query else parse_message(safe)
    if event is None:
        return []
    role, crew = ROLES[guest["role"]]
    return [event.model_copy(update={"id": route["id"], "sender": f"Guest ({guest['name']})",
                                     "sender_role": f"{role} ({crew})", "thread": "Synthetic demo guest",
                                     "subject": None})]


@contextmanager
def delivery_scope(event_ids: list[str]):
    route = next((event_id for event_id in reversed(event_ids)
                  if event_id.startswith("guest-") or store().get("guest_routes", event_id)), None)
    token = _cause.set(route)
    try:
        yield
    finally:
        _cause.reset(token)


def public_sources(sources: list[m.Evidence]) -> list[m.Evidence]:
    return [source.model_copy(update={"sender": "Guest"})
            if source.event_id.startswith("guest-") or store().get("guest_routes", source.event_id)
            else source for source in sources]


def crew(event_id: str) -> str | None:
    route = store().get("guest_routes", event_id)
    guest = store().get("guests", route["guest"]) if route else None
    return ROLES[guest["role"]][1] if guest and guest.get("role") in ROLES else None


def bind_delivery(message: m.OutboundMessage, event_ids: list[str]) -> m.OutboundMessage:
    """Bind the actual sources, including an explicit ordinary route for unrelated timer messages."""
    with _lock:
        saved = store().get("guest_deliveries", message.id)
        if saved is None:
            sources = [*event_ids, *([message.in_reply_to] if message.in_reply_to else [])]
            route = next((source for source in reversed(sources)
                          if source.startswith("guest-") or store().get("guest_routes", source)), None)
            saved = {"route": route}
            store().put("guest_deliveries", message.id, saved)
        return message.model_copy(update={"channel": "telegram"}) if saved.get("route") else message


def target(message: m.OutboundMessage) -> tuple[str, int | None] | None:
    """Resolve a reply or a notice caused by a guest without putting its chat id on the public message."""
    with _lock:
        s = store()
        saved = s.get("guest_deliveries", message.id)
        route_id = (saved.get("route") or "") if saved is not None else message.in_reply_to or _cause.get() or ""
        route = s.get("guest_routes", route_id)
        if route is None:
            if route_id.startswith("guest-"):
                raise ValueError("guest reply has no active private route")
            return None
        guest = s.get("guests", route["guest"])
        if guest is None:
            raise ValueError("guest reply has no active private route")
        s.put("guest_deliveries", message.id, {"route": route["id"]})
        return guest["chat"], route["message"] if message.in_reply_to else None
