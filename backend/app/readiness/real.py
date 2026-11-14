"""Read tomorrow's tasks from the current plan and send one briefing per crew."""
import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePosixPath

from app.core import config, pipeline, site
from app.core import models as m
from app.core.registry import area
from app.core.store import store
from app.language import localize
from app.live import delivery, directory
from app.readiness import sent
from app.speech import limit, script, speak

log = logging.getLogger(__name__)


def _at() -> datetime:
    times = [datetime.fromisoformat(event['received_at'].replace('Z', '+00:00'))
             for event in store().list('events')]
    return max(times) if times else datetime.now(timezone.utc)


def evaluate(day: date | None = None) -> m.Readiness:
    with pipeline._lock:
        return _evaluate(day)


def _evaluate(day: date | None = None) -> m.Readiness:
    generated = _at()
    target = day or (generated + timedelta(days=1)).date()
    raw = store().get('plan', 'current')
    plan = m.Plan.model_validate(raw) if raw else area('schedule').baseline()
    items = []
    for task in sorted(plan.tasks, key=lambda task: task.start):
        if task.start.date() != target:
            continue
        check = area('gate').check(m.StartCheckRequest(asked_by='readiness', task_id=task.id))
        if check.allowed == 'unknown':
            status = 'unknown'
        elif any(reason.blocking for reason in check.reasons):
            status = 'blocked'
        else:
            status = 'at_risk' if check.reasons else 'ready'
        items.append(m.ReadinessItem(task_id=task.id, name=task.name, unit=task.unit,
                                     crew=task.crew, start=task.start, status=status, reasons=check.reasons))
    return m.Readiness(day=target, generated_at=generated, items=items, briefings=[])


def _channel(crew: str) -> str:
    # Prefer an explicit crew/foreman address over the shared Telegram fallback.
    contact = directory.lookup(crew)
    if contact:
        for channel in directory.CHANNELS:
            if getattr(contact, channel):
                return channel
    for channel in ('email', 'whatsapp', 'telegram'):
        if directory.reach(crew, channel):
            return channel
    return 'telegram'


def _media(items: list[m.ReadinessItem]) -> str | None:
    sources = {source.event_id for item in items for reason in item.reasons
               if reason.kind in ('superseded_drawing', 'drawing_not_confirmed') for source in reason.sources}
    revisions = {(fact['data'].get('sheet'), fact['data'].get('revision'))
                 for fact in store().list('facts')
                 if fact.get('event_id') in sources and fact.get('type') == 'drawing_revision'}
    for diff in reversed(store().list('diffs')):
        if (diff['sheet'], diff['to_rev']) not in revisions:
            continue
        overlay = diff['overlay_url']
        if overlay.startswith('/media/files/'):
            for name in ('crop.png', 'crop.svg'):
                url = str(PurePosixPath(overlay).with_name(name))
                root = config.data_dir().resolve()
                path = (root / url.removeprefix('/media/')).resolve()
                if root in path.parents and path.is_file():
                    return url
        return overlay
    return None


def _translated(text: str, language: str, message: m.OutboundMessage, crew: str) -> str:
    """The spoken script in the crew's language, without the English copy the written message carries."""
    try:
        original = m.OutboundMessage(id=f'{message.id}-spoken', channel=message.channel, to=crew, text=text,
                                     reason=message.reason, created_at=message.created_at)
        translated = localize(original, language).text.split('\n\n', 1)[0].strip()
    except Exception:
        return text
    return limit(translated) or text


def _spoken(message: m.OutboundMessage, crew: str) -> str | None:
    """The clip of this briefing in the crew's language, or None: a briefing without a clip still goes out."""
    spoken = script(message)
    if not spoken:
        return None
    language = (directory.language(crew, message.channel) or 'en').strip().lower()
    if language[:2] != 'en':
        spoken = _translated(spoken, language, message, crew)
    return speak(spoken, language)


def briefing_id(day: date, crew: str) -> str:
    """The outbox id of one crew's briefing for one day: derived from day and crew, so a lookup needs no build."""
    key = hashlib.sha256(crew.strip().casefold().encode()).hexdigest()[:16]
    return f'o-briefing-{day.isoformat()}-{key}'


def _message(picture: m.Readiness, crew: str) -> m.OutboundMessage:
    own = [item for item in picture.items if item.crew == crew]
    tasks = [f'{item.name} at {site.local(item.start):%H:%M}' + (f' in {item.unit}' if item.unit else '') for item in own]
    lines = [f'{picture.day:%A %d %B} for {crew} (site time): ' + ', '.join(tasks)]
    points = sorted(((item, reason) for item in own for reason in item.reasons),
                    key=lambda pair: (not pair[1].blocking, pair[1].kind, pair[0].start))
    for item, reason in points:
        sources = ', '.join(source.event_id for source in reason.sources)
        lines.append(f'Before you start {item.name}: {reason.text}' + (f' [{sources}]' if sources else ''))
    if not points:
        lines.append('All clear for these tasks based on the current record.')
    message = m.OutboundMessage(id=briefing_id(picture.day, crew), channel=_channel(crew),
                                to=crew, text='\n'.join(lines), buttons=['Got it'], media_url=_media(own),
                                reason=f'Tomorrow on site, {picture.day.isoformat()}', created_at=picture.generated_at)
    # The spoken clip replaces the picture: one message carries one medium, and a crew can listen on site.
    clip = _spoken(message, crew)
    return message.model_copy(update={'media_url': clip}) if clip else message


def run(day: date | None = None) -> m.Readiness:
    with pipeline._lock:
        picture = evaluate(day)
        now = datetime.now(timezone.utc)
        for crew in dict.fromkeys(item.crew for item in picture.items):
            key = briefing_id(picture.day, crew)
            previous = store().get('outbox', key)
            # Looked up before the message is built, so a briefing that already went out costs no clip and no
            # translation. The state file outlives a demo reset, which the outbox does not.
            if sent.is_sent(picture.day, crew) or (previous and previous.get('status') in delivery.DONE):
                if previous and previous.get('status') in delivery.DONE and not sent.is_sent(picture.day, crew):
                    sent.record(picture.day, crew, 'sent', now)
                continue
            if not sent.may_try(picture.day, crew, now):
                log.warning('readiness: briefing for %s on %s is not retried now', crew, picture.day.isoformat())
                continue
            # Preserve the original pending content and channel on a retry.
            message = (m.OutboundMessage.model_validate(previous) if previous else _message(picture, crew))
            result = delivery.deliver(message)
            sent.record(picture.day, crew, result.status, now)
            picture.briefings.append(result)
            sources = sorted({source.event_id for item in picture.items if item.crew == crew
                              for reason in item.reasons for source in reason.sources})
            store().put('record', 'r-' + message.id, m.RecordEntry(
                id='r-' + message.id, at=picture.generated_at, kind='notice', actor='Aurora',
                title=f'Briefing for {crew}: {result.status}', detail=result.text,
                source_event_ids=sources, refs={'message': message.id}))
        return picture
