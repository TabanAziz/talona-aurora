"""Report effective local configuration without probing providers or exposing credentials."""
import os

from app.core import config
from app.core.registry import is_mock
from app.core.store import store
from . import channels


def _present(*names: str) -> bool:
    return all(bool(os.environ.get(name, "").strip()) for name in names)


def snapshot() -> dict:
    custom = config.project_directory.get() is not None
    project_id = (store().get("project", "current") or {}).get("id", config.project_id.get())
    connections = []
    for name, label, service, keys in (
        ("telegram", "Telegram", "telegram_api", ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")),
        ("email", "Email", "email_api", ("EMAIL_ADDRESS", "EMAIL_APP_PASSWORD")),
        ("whatsapp", "WhatsApp", "whatsapp_api", ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM")),
        ("llm", "Project intelligence", "llm", ("MISTRAL_API_KEY", "LLM_MODEL")),
        ("voice", "Voice transcription", "voice_api", ("ELEVENLABS_API_KEY",)),
    ):
        channel = name in ("telegram", "email", "whatsapp")
        mocked = config.external_is_mock(service) or (name != "llm" and is_mock(name))
        configured = _present(*keys)
        bound = (channels.allowed(name) or channels.allowed(name, "inbound")) if name in channels.CHANNELS else not custom
        if channel and not bound:
            status, detail = "unconfigured", "This project's messaging channel is not bound to the configured account."
        elif mocked:
            status, detail = "simulated", "Simulated provider; no live network calls are enabled."
        elif configured:
            status, detail = "configured", "Local credentials configured. Provider connectivity has not been checked."
        else:
            status, detail = "unconfigured", "Required provider configuration is missing."
        enabled = channel and status == "configured"
        connections.append({"id": name, "label": label, "status": status,
                            "inbound_enabled": enabled and (channels.allowed(name, "inbound") if name in channels.CHANNELS else True),
                            "outbound_enabled": enabled and (channels.allowed(name) if name in channels.CHANNELS else True), "detail": detail})
    return {"project_id": project_id, "is_default": not custom, "connections": connections}
