"""Who may post to the Telegram webhook.

The sender of an update is resolved by display name, so a forged update could speak as anyone on the
project. Telegram proves an update is its own by sending the `secret_token` given to setWebhook in the
header below. Without TELEGRAM_WEBHOOK_SECRET every request is accepted, so the hosted app keeps working
until a human sets the secret on the machine and on the webhook.
"""
import hmac
import os

HEADER = "X-Telegram-Bot-Api-Secret-Token"

# Updates Telegram sends that Aurora never turns into an event. Named here so the route can say why it dropped one.
MEMBERSHIP_KEYS = ("my_chat_member", "chat_member", "new_chat_members", "left_chat_member")


def _secret() -> str:
    return os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()


def update_id(update: object) -> object:
    """The id Telegram gave the update, or a question mark: it is the only handle a dropped update has."""
    if isinstance(update, dict):
        return update.get("update_id", "?")
    return "?"


def drop_reason(update: object) -> str | None:
    """Why this update became no event, in the words the log line uses, or None when it is not a known case."""
    if not isinstance(update, dict):
        return "not an update object"
    for key in ("edited_message", "edited_channel_post"):
        if key in update:
            return "edited message"
    if "channel_post" in update:
        return "channel post"
    if any(key in update for key in MEMBERSHIP_KEYS):
        return "membership change"
    message = update.get("message") or {}
    if isinstance(message, dict):
        if message.get("photo") and not (message.get("text") or message.get("caption")):
            return "photo without caption"
        if message.get("document") and not (message.get("text") or message.get("caption")):
            return "file without caption"
    if "callback_query" in update:
        return "button press that is not a briefing acknowledgement"
    return None


def allowed(header: str | None) -> bool:
    """True when no secret is configured, or the header carries exactly the configured secret."""
    secret = _secret()
    if not secret:
        return True
    if header is None:
        return False
    return hmac.compare_digest(header.encode("utf-8"), secret.encode("utf-8"))
