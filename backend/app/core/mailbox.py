"""Background loop that reads the project mailbox while the app runs.

It runs only when the mailbox is live (USE_MOCK_EMAIL_API=false), so no test and no e2e run starts it. A failing
poll is logged and tried again at the next round; it never stops the app.
"""
import asyncio
import logging
import os
import time
from collections.abc import Callable

from . import config, pipeline
from . import models as m
from .registry import area
from .store import store

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 20.0
# A broken mailbox retries every round; one entry per window is enough to tell the operator to fall back.
QUIET_S = 300.0
_last_report: float | None = None


def enabled() -> bool:
    return not config.external_is_mock("email_api")


def interval_s() -> float:
    try:
        return max(1.0, float(os.environ.get("EMAIL_POLL_INTERVAL_S") or DEFAULT_INTERVAL_S))
    except ValueError:
        return DEFAULT_INTERVAL_S


def _report_failure(error: Exception) -> None:
    """Write one visible entry so the operator knows to fall back, at most once per quiet window.

    The error text stays out of the record: a mailbox error can carry an address or a credential.
    """
    global _last_report
    now = time.monotonic()
    if _last_report is not None and now - _last_report < QUIET_S:
        return
    _last_report = now
    entry_id = f"r-mailbox-{int(now)}"
    try:
        store().put("record", entry_id, m.RecordEntry(
            id=entry_id, at=pipeline.now(), kind="info", actor="Aurora",
            title="Mailbox unreachable",
            detail=f"Aurora could not read the project mailbox ({type(error).__name__}) and will try again. "
                   f"Use Play next event to keep the demo moving.",
        ))
    except Exception as store_error:
        log.error("mailbox: the failure entry was not stored: %s", type(store_error).__name__)


def poll_once(
    poll: Callable[[], list[m.InboundEvent]] | None = None,
    ingest: Callable[[m.InboundEvent], m.IngestResult] = pipeline.ingest,
) -> int:
    from app.workspace.channels import selected
    with selected("email") as enabled:
        return _poll_once(poll, ingest) if enabled else 0


def _poll_once(poll, ingest) -> int:
    """One round: poll the mailbox and ingest each mail. Returns how many events were new."""
    try:
        events = (poll or area("email").poll)()
    except Exception as error:
        log.warning("mailbox poll failed: %s", type(error).__name__)
        _report_failure(error)
        return 0
    new = 0
    for event in events:
        try:
            if not ingest(event).duplicate:
                new += 1
        except Exception:
            log.exception("mail %s could not be ingested", event.id)
    if new:
        log.info("mailbox: %d new event(s)", new)
    return new


async def run(poll=None, ingest=pipeline.ingest, interval: float | None = None) -> None:
    while True:
        await asyncio.to_thread(poll_once, poll, ingest)
        await asyncio.sleep(interval if interval is not None else interval_s())


def start() -> asyncio.Task | None:
    """Start the loop in the running event loop when the mailbox is live, otherwise do nothing."""
    if not enabled():
        return None
    log.info("mailbox loop on, every %.0f s", interval_s())
    return asyncio.create_task(run())


async def stop(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
