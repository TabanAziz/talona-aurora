"""A briefing button acknowledges its message, never a drawing revision."""
from app.core import models as m, pipeline
from app.core.store import store


def accept(query: dict | None, event: m.InboundEvent) -> m.IngestResult | None:
    if not query or event.channel != 'telegram':
        return None
    data = query.get('data')
    if not isinstance(data, str) or not data.startswith('0:o-briefing-'):
        return None
    message_id = data[2:]
    keyboard = ((query.get('message') or {}).get('reply_markup') or {}).get('inline_keyboard') or []
    if not any(button.get('callback_data') == data for row in keyboard for button in row):
        return None
    with pipeline._lock:
        s = store()
        message = s.get('outbox', message_id)
        if not message or message.get('channel') != 'telegram' or message.get('buttons') != ['Got it']:
            return None
        if message.get('status') not in ('sent', 'simulated'):
            return None
        if s.get('events', event.id):
            return m.IngestResult(event_id=event.id, duplicate=True)
        s.put('events', event.id, event)
        entry = m.RecordEntry(id='r-briefing-ack-' + event.id, at=event.received_at,
                              kind='acknowledgement', actor=event.sender,
                              title=f"{event.sender} acknowledged the briefing for {message['to']}",
                              detail=message['reason'], source_event_ids=[event.id], refs={'message': message_id})
        s.put('record', entry.id, entry)
        return m.IngestResult(event_id=event.id)
