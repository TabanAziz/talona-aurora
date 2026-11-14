"""Which briefings already went out for a day, and when a failed one may be tried again.

The outbox is the record of what was sent, but a demo reset clears the store, and the scheduler ticks again a
minute later. So the briefing state also lives in a small file under DATA_DIR, which a reset does not touch:
one entry per crew and day, with the last status, the time of the last attempt and how many attempts failed.

The file is not a store collection, so no contract changes. It is small, it is written under the same lock as
the outbox, and a missing or unreadable file only means "nothing has been sent today yet".
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.core import config

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
SPACING = timedelta(minutes=10)
DONE = ('sent', 'simulated')


def _path() -> Path:
    folder = config.data_dir() / 'readiness'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / 'briefings.json'


def _read() -> dict:
    path = _path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        log.warning('readiness: the briefing state file is not readable, starting from nothing')
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    _path().write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _key(day: date, crew: str) -> str:
    return f'{day.isoformat()}|{crew.strip().casefold()}'


def entry(day: date, crew: str) -> dict:
    return _read().get(_key(day, crew)) or {}


def is_sent(day: date, crew: str) -> bool:
    return entry(day, crew).get('status') in DONE


def may_try(day: date, crew: str, now: datetime) -> bool:
    """True when this briefing has not gone out and its last failed attempt is old enough to try again."""
    state = entry(day, crew)
    if state.get('status') in DONE:
        return False
    if int(state.get('attempts') or 0) >= MAX_ATTEMPTS:
        return False
    last = state.get('at')
    if not last:
        return True
    try:
        at = datetime.fromisoformat(str(last).replace('Z', '+00:00'))
    except ValueError:
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return now - at >= SPACING


def record(day: date, crew: str, status: str, now: datetime | None = None) -> dict:
    """Store the outcome of one attempt: a done status stops the day, a failure counts up and sets the time."""
    now = now or datetime.now(timezone.utc)
    data = _read()
    key = _key(day, crew)
    state = data.get(key) or {}
    if status in DONE:
        state = {'status': status, 'at': now.isoformat(), 'attempts': 0}
    else:
        state = {'status': status, 'at': now.isoformat(), 'attempts': int(state.get('attempts') or 0) + 1}
    data[key] = state
    _write(data)
    return state
