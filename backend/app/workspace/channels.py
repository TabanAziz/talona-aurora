"""Explicit ownership of the locally configured messaging accounts, without copying secrets."""
import os
from contextlib import contextmanager

from app.core import config
from app.core.registry import is_mock
from . import storage

CHANNELS = ("telegram", "email")
KEYS = {"telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
        "email": ("EMAIL_ADDRESS", "EMAIL_APP_PASSWORD")}


def binding(channel: str) -> dict | None:
    return storage.catalog().get("channel_targets", channel)


def configured(channel: str) -> bool:
    return all(bool(os.environ.get(key, "").strip()) for key in KEYS[channel])


def target_id(channel: str) -> str:
    row = binding(channel)
    return row["project_id"] if row else storage.default_project()["id"]


def current_id() -> str:
    return config.project_id.get() or storage.default_project()["id"]


def allowed(channel: str, direction: str = "outbound") -> bool:
    if channel not in CHANNELS:
        return config.project_directory.get() is None
    row = binding(channel)
    if row is None:
        return config.project_directory.get() is None
    return (current_id() == row["project_id"] and row.get(f"{direction}_enabled", False)
            and not storage.is_deleted(row["project_id"]) and configured(channel))


def group_chat() -> str | None:
    row = binding("telegram")
    if not (allowed("telegram") or allowed("telegram", "inbound")) or (row and not row.get("telegram_group")):
        return None
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip() or None


def accepts_telegram(update: dict) -> bool:
    row = binding("telegram")
    if not row:
        return True
    if not allowed("telegram", "inbound"):
        return False
    message = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    return str((message.get("chat") or {}).get("id", "")) == (group_chat() or "")


@contextmanager
def selected(channel: str):
    project_id = target_id(channel)
    default = storage.default_project()["id"]
    path = None if project_id == default else storage.directory(project_id)
    with storage.selected(project_id, path):
        yield allowed(channel, "inbound")


def snapshot() -> dict:
    result = {}
    for channel in CHANNELS:
        row = binding(channel) or {}
        mocked = config.external_is_mock(f"{channel}_api") or is_mock(channel)
        ready = configured(channel) and not mocked and not storage.is_deleted(target_id(channel))
        result[channel] = {"project_id": target_id(channel), "explicit": bool(row),
            "inbound_enabled": ready and row.get("inbound_enabled", True),
            "outbound_enabled": ready and row.get("outbound_enabled", True),
            "configured": configured(channel), "simulated": mocked,
            "telegram_group": bool(row.get("telegram_group", False)),
            "runtime": storage.catalog().get("channel_runtime", channel)}
    return {"channels": result}


def bind(body: dict) -> dict:
    project_id = body.get("project_id")
    if not isinstance(project_id, str):
        raise ValueError("project_id is required")
    storage.safe(project_id)
    default = storage.default_project()["id"]
    if storage.is_deleted(project_id) or (project_id != default and not storage.catalog().get("projects", project_id)):
        raise ValueError("Project not found")
    requested = [channel for channel in CHANNELS if channel in body]
    if not requested:
        raise ValueError("Choose telegram and/or email as true or false")
    for name in (*requested, "inbound_enabled", "outbound_enabled", "telegram_group"):
        if name in body and not isinstance(body[name], bool):
            raise ValueError(f"{name} must be a boolean")
    for channel in requested:
        if body[channel] and not configured(channel):
            raise ValueError(f"Required {channel} configuration is missing")
        if channel == "telegram" and body[channel] and not body.get("telegram_group", False):
            raise ValueError("Explicit telegram_group=true is required to use the configured demo group")
    with storage.LOCK:
        for channel in requested:
            storage.catalog().put("channel_targets", channel, {
                "project_id": project_id, "inbound_enabled": body[channel] and body.get("inbound_enabled", True),
                "outbound_enabled": body[channel] and body.get("outbound_enabled", True),
                "telegram_group": channel == "telegram" and body.get("telegram_group", False),
                "updated_at": storage.now()})
    return snapshot()
