"""Replay measured wrong-unit transcripts through the real read-back pipeline, without providers."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import timedelta
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def run():
    from app import voicecheck
    from app.core import config, llm, models, pipeline
    from app.core import store as storage
    from app.voicecheck import record as fixture

    original = (HERE / 'measurements.json').read_bytes()
    measured = json.loads(original)['rows']
    failures = [row for row in measured if row['id'] == 'e53' and row['added_snr_db'] in (5, 0)]
    assert len(failures) == 2
    corrected = next(row['transcript'] for row in measured if row['id'] == 'e53' and row['added_snr_db'] is None)
    assert corrected == fixture.SAID
    raw = next(event for event in json.loads((ROOT / 'data/messages/events.json').read_text()) if event['id'] == 'e53')
    results = []
    with tempfile.TemporaryDirectory(prefix='aurora-voice-safeguard-') as scratch, patch.dict(os.environ, clear=False):
        os.environ['DATA_DIR'] = scratch
        os.environ['SITE_TIMEZONE'] = 'Europe/Berlin'
        os.environ.pop('DEMO_ANCHOR', None)
        for name in config.AREAS:
            os.environ['USE_MOCK_' + name.upper()] = 'false'
        for name in config.EXTERNAL:
            os.environ['USE_MOCK_' + name.upper()] = 'true'
        storage._store = None
        try:
            with patch.object(llm, '_call', side_effect=AssertionError('No provider calls allowed')):
                for row in failures:
                    pipeline.reset()
                    db = storage.store()
                    note = models.InboundEvent.model_validate({**raw, 'transcript': row['transcript']})
                    held = pipeline.ingest(note)
                    assert not held.facts and not held.flags and not held.record and held.answer is None
                    assert not [fact for fact in db.list('facts') if fact['event_id'] == note.id]
                    [readback] = held.outbox
                    assert readback.status == 'simulated' and row['transcript'] in readback.text
                    assert db.get('voicechecks', note.id)['status'] == 'open'
                    pipeline.ingest(fixture.answer('e53-correct', timedelta(minutes=1), voicecheck.CORRECT, readback.text))
                    answer = fixture.answer('e53-text', timedelta(minutes=2), corrected)
                    pipeline.ingest(answer)
                    facts = [fact for fact in db.list('facts') if fact['event_id'] == note.id]
                    units = fixture.units(facts)
                    assert '3B' in units and '3D' not in units
                    check = db.get('voicechecks', note.id)
                    assert check['heard'] == row['transcript'] and check['corrected'] == corrected
                    assert check['status'] == 'corrected'
                    before = {name: db.list(name) for name in ('facts', 'flags', 'record', 'outbox')}
                    pipeline.ingest(answer)
                    assert {name: db.list(name) for name in before} == before
                    results.append({'added_snr_db': row['added_snr_db'], 'audio_sha256': row['audio_sha256'],
                        'original_heard': row['transcript'], 'original_source_text': row['source_text'],
                        'held_before_confirmation': True, 'facts_before_confirmation': 0,
                        'scripted_correction': corrected, 'correction_source': 'measured baseline transcript',
                        'corrected_units': sorted(units), 'heard_preserved': True,
                        'repeat_added_nothing': True, 'provider_calls': 0, 'delivery': 'simulated'})
        finally:
            if storage._store is not None:
                storage._store._db.close()
                storage._store = None
    assert (HERE / 'measurements.json').read_bytes() == original
    report = {'kind': 'separate read-back safeguard proof',
        'measurements_sha256': hashlib.sha256(original).hexdigest(),
        'original_stt_result_changed': False, 'new_speech_calls': 0,
        'limitation': 'Recorded provider responses and scripted sender correction; no human interaction or improved recognition proved.',
        'cases': results}
    (HERE / 'safeguard.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    report = run()
    print(f"PASS: {len(report['cases'])} measured wrong-unit transcripts held, corrected to 3B once; original measurements unchanged; no provider calls")
