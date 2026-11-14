"""Run the site's daily briefing from the app lifecycle."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from app.core import config, site
from app.core.registry import area, is_mock

log = logging.getLogger(__name__)


def hour() -> int:
    try:
        value = int(os.environ.get('BRIEFING_HOUR', '16'))
    except ValueError:
        return 16
    return value if 0 <= value <= 23 else 16


def tick(now: datetime | None = None):
    from app.workspace.channels import selected
    with selected("telegram") as enabled:
        return _tick(now) if enabled else None


def _tick(now: datetime | None = None):
    local = site.local(now or datetime.now(timezone.utc))
    if local.hour < hour():
        return None
    return area('readiness').run(local.date() + timedelta(days=1))


async def loop():
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception as error:
            log.error('readiness briefing failed: %s', type(error).__name__)
        await asyncio.sleep(60)


def start():
    if is_mock('readiness') or all(config.external_is_mock(name) for name in ('telegram_api', 'email_api', 'whatsapp_api')):
        return None
    return asyncio.create_task(loop())


async def stop(task):
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
