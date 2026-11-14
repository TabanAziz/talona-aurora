"""Opt-in local Bot API polling; never modifies a hosted bot's webhook."""
import asyncio
import hashlib
import logging
import os
import tempfile
import threading
from contextlib import contextmanager, nullcontext
from pathlib import Path

from fastapi import BackgroundTasks

from app.core import config
from app.core.registry import is_mock
from app.workspace import channels, storage
from . import real

log = logging.getLogger(__name__)
_lock = threading.Lock()
_leased = False


def enabled() -> bool:
    return config.flag("TELEGRAM_POLL_ENABLED") is True


def _account_key() -> str:
    return hashlib.sha256(os.environ.get("TELEGRAM_BOT_TOKEN", "").encode()).hexdigest()


def _status(status: str, detail: str, **counts) -> dict:
    result = {"status": status, "detail": detail, **counts}
    storage.catalog().put("channel_runtime", "telegram", {**result, "checked_at": storage.now()})
    return result


@contextmanager
def _account_lock():
    digest = _account_key()
    path = Path(tempfile.gettempdir()) / f"aurora-telegram-{digest}.lock"
    handle = path.open("a+b")
    acquired = False
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            pass
        yield acquired
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def poll_once() -> dict:
    if not enabled():
        return _status("disabled", "Local Telegram polling is disabled.")
    if not channels.binding("telegram"):
        return _status("unconfigured", "Bind the configured Telegram account to a project first.")
    if config.external_is_mock("telegram_api") or is_mock("telegram"):
        return _status("simulated", "Telegram is simulated; no polling request was sent.")
    if not channels.configured("telegram"):
        return _status("unconfigured", "Required Telegram configuration is missing.")
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "detail": "A polling round is already running."}
    try:
        with (nullcontext(True) if _leased else _account_lock()) as acquired:
            if not acquired:
                return _status("busy", "Another local Aurora process is polling this account.")
            with channels.selected("telegram") as inbound:
                if not inbound:
                    return _status("disabled", "The bound project is unavailable or inbound messaging is disabled.")
                try:
                    if real._api("getWebhookInfo", {}).get("url"):
                        return _status("blocked", "An active Telegram webhook owns this bot. Local polling did not change it.")
                    cursor = storage.catalog().get("channel_offsets", "telegram") or {}
                    offset = cursor.get("next_update_id", 0) if cursor.get("account") == _account_key() else 0
                    updates = real._api("getUpdates", {"offset": offset,
                                        "limit": 20, "timeout": 0,
                                        "allowed_updates": ["message", "callback_query"]})
                    from app.core.main import telegram_webhook
                    received = ingested = 0
                    for update in updates:
                        tasks = BackgroundTasks()
                        result = telegram_webhook(update, tasks)
                        for task in tasks.tasks:
                            task.func(*task.args, **task.kwargs)
                        received += result["received"]
                        ingested += result["ingested"]
                        storage.catalog().put("channel_offsets", "telegram", {"next_update_id": int(update["update_id"]) + 1,
                                                                                "account": _account_key()})
                    return _status("receiving", "Local polling is reading the explicitly bound project group.",
                                   received=received, ingested=ingested)
                except Exception as error:
                    log.warning("Telegram polling failed: %s", type(error).__name__)
                    return _status("error", f"Telegram polling failed ({type(error).__name__}); no account configuration was changed.")
    finally:
        _lock.release()


async def run():
    global _leased
    while True:
        with _account_lock() as acquired:
            if not acquired:
                _status("busy", "Another local Aurora process owns this account's polling lease.")
                await asyncio.sleep(3)
                continue
            _leased = True
            try:
                while True:
                    round_task = asyncio.create_task(asyncio.to_thread(poll_once))
                    try:
                        await asyncio.shield(round_task)
                    except asyncio.CancelledError:
                        await round_task
                        raise
                    await asyncio.sleep(3)
            finally:
                _leased = False


def start():
    return asyncio.create_task(run()) if enabled() else None


async def stop(task):
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
