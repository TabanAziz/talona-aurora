"""Deliberate real-service evaluation; default mode only scores committed measurements."""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from make_noise import HERE, ROOT, LEVELS, build, read_wave
from score import summarize


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def fingerprint(files, context):
    digest = hashlib.sha256(json.dumps(context, sort_keys=True).encode())
    for path in files:
        digest.update(str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def metered(measured, path, service, invoke, seconds=0):
    meta = measured['meta']
    if service == 'speech':
        if meta['speech_requests'] >= 60 or meta['audio_seconds'] + seconds > 326:
            raise RuntimeError('Estimated full-run speech budget exhausted')
        meta['speech_requests'] += 1
        meta['audio_seconds'] += seconds
    else:
        if meta['model_requests'] >= 120:
            raise RuntimeError('Estimated full-run extraction budget exhausted')
        meta['model_requests'] += 1
    save(path, measured)
    return invoke()


def render(report):
    meta = report['meta']
    lines = ['# Voice notes with site noise', '',
             f"Measured at {meta['when']}; speech model {meta['speech_model']}; extraction model {meta['model']}.",
             f"Complete six-note/four-level matrix: {report['complete']}.",
             report['scope'],
             f"Speech requests reserved/attempted: {meta['speech_requests']}; audio budgeted including retries: {meta['audio_seconds']:.2f} s; model requests reserved/attempted: {meta['model_requests']}.",
             '', '| Added SNR | n | All keys retained | Same facts | Safely rejected | Wrong unit/sheet/revision |',
             '|---|---:|---:|---:|---:|---:|']
    for level in report['levels']:
        n = level['n']
        lines.append(f"| {level['added_snr_db']} dB | {n} | {level['keys_retained']}/{n} | {level['same_facts']}/{n} | {level['safe_failures']}/{n} | {level['wrong_critical_facts']}/{n} |")
    first = report['first_failing_added_snr_db']
    lines += ['', f"First failing added-noise level among valid baselines (20 to 0 dB): {'none observed' if first is None else str(first) + ' dB'}.",
              f"First transcript key loss: {report['first_key_loss_added_snr_db']} dB; first accepted wrong unit or revision: {report['first_wrong_unit_or_revision_added_snr_db']} dB.",
              'Invalid baselines (not evidence of noise tolerance): ' + (', '.join(report['invalid_baseline_ids']) or 'none') + '.',
              '', '## What this does not test', '', *['- ' + text for text in report['limitations']],
              '', '## Baselines and every measured transcript', '']
    for row in [*report['baselines'], *report['results']]:
        level = 'supplied recording baseline' if row['added_snr_db'] is None else f"added {row['added_snr_db']} dB"
        lines += [f"### {row['id']}, {level}", '', f"Transcript: {row['transcript'] or '(empty)'}", '',
                  'Source recording: ' + ('no generated noise' if row['source_noise_snr_db'] is None else f"already noisy at {row['source_noise_snr_db']} dB") + '.',
                  f"Elapsed: {row['elapsed_s']:.2f} s."]
        if 'keys_retained' in row:
            lines += [f"Keys retained: {row['keys_retained']}; same facts: {row['same_facts']}; safely rejected: {row['safe_failure']}.",
                      'Failed key checks: ' + (', '.join(key for key, value in row['key_checks'].items() if not value) or 'none'),
                      'Wrong critical values: ' + json.dumps(row['wrong_critical_values'])]
        lines += ['', 'Facts: ' + json.dumps(row['facts'], ensure_ascii=False), '']
    return '\n'.join(lines).rstrip()


def estimate():
    rows = json.loads((ROOT / 'data/voice/manifest.json').read_text(encoding='utf-8'))
    baseline = sum(len(samples) / rate for samples, rate in
                   (read_wave(ROOT / 'data/voice' / row['file']) for row in rows))
    print(f'Full matrix: 30 speech calls, {baseline * 5:.2f} audio seconds; at most 60 calls/{baseline * 10:.2f}s with one retry each.')
    print('Extraction: 30 initial calls, at most 60 with repair, at most 120 transport attempts including retries.')


def live(args):
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.core import config, llm, models, store as storage
    from app.extract import real as extract
    from app.voice import real as voice
    from app.record import real as record
    from app.schedule import real as schedule
    config.load_dotenv()
    for name in ('MISTRAL_API_KEY', 'LLM_MODEL', 'ELEVENLABS_API_KEY'):
        if not os.environ.get(name):
            raise SystemExit(name + ' missing; no service call made')
    for service in config.EXTERNAL:
        os.environ['USE_MOCK_' + service.upper()] = 'false' if service in ('llm', 'voice_api') else 'true'
    os.environ.pop('DEMO_ANCHOR', None)
    os.environ['LLM_RECORD'] = 'false'
    manifest = json.loads((ROOT / 'data/voice/manifest.json').read_text(encoding='utf-8'))
    events = {event['id']: event for event in json.loads((ROOT / 'data/messages/events.json').read_text(encoding='utf-8'))}
    build()
    now = datetime.now(timezone.utc).isoformat()
    project, plan = record.project(), schedule.baseline()
    context = {'project': project.model_dump(mode='json'), 'plan': plan.model_dump(mode='json'),
               'events': {row['id']: events[row['id']] for row in manifest},
               'timezone': os.environ.get('SITE_TIMEZONE') or extract.DEFAULT_SITE_TIMEZONE,
               'llm_base_url': os.environ.get('LLM_BASE_URL') or 'https://api.mistral.ai/v1',
               'llm_model': os.environ['LLM_MODEL'], 'speech_model': voice.MODEL_ID}
    source_hash = fingerprint(sorted(path for path in (ROOT / 'backend/app').rglob('*.py')
                                     if not path.name.startswith('test_')), context)
    meta = {'when': now, 'speech_model': voice.MODEL_ID, 'model': os.environ['LLM_MODEL'], 'provenance_version': 2,
            'implementation_sha256': source_hash, 'speech_requests': 0, 'model_requests': 0, 'audio_seconds': 0.0}
    measured = {'meta': meta, 'rows': []}
    path = HERE / 'measurements.json'
    if args.resume and path.is_file():
        previous = json.loads(path.read_text(encoding='utf-8'))
        if any(previous['meta'].get(key) != meta[key] for key in ('speech_model', 'model', 'implementation_sha256', 'provenance_version')):
            raise SystemExit('Model or implementation changed; existing measurements cannot be resumed')
        measured = previous
        meta = measured['meta']
    post_voice, attempt_llm = voice._post, llm._attempt
    def counted_voice(audio, *positional, **kwargs):
        with wave.open(io.BytesIO(audio), 'rb') as source:
            seconds = source.getnframes() / source.getframerate()
        return metered(measured, path, 'speech', lambda: post_voice(audio, *positional, **kwargs), seconds)
    def counted_llm(*positional, **kwargs):
        return metered(measured, path, 'model', lambda: attempt_llm(*positional, **kwargs))
    voice._post, llm._attempt = counted_voice, counted_llm
    try:
        with tempfile.TemporaryDirectory(prefix='aurora-voice-eval-') as directory:
            os.environ['DATA_DIR'] = directory
            storage._store = None
            storage.store().put('project', 'current', project)
            storage.store().put('plan', 'current', plan)
            media = Path(directory) / 'files'
            media.mkdir()
            try:
                for source in manifest:
                    if args.only and source['id'] not in args.only:
                        continue
                    for level in [None, *args.levels]:
                        audio = (ROOT / 'data/voice' / source['file'] if level is None
                                 else HERE / 'clips' / f"{source['id']}-{level}db.wav")
                        digest = hashlib.sha256(audio.read_bytes()).hexdigest()
                        existing = next((row for row in measured['rows'] if row['id'] == source['id'] and row['added_snr_db'] == level), None)
                        if existing:
                            if existing['audio_sha256'] != digest:
                                raise RuntimeError('Audio changed; cannot reuse a previous measurement')
                            print(f"{source['id']} {level}: existing measurement retained", flush=True)
                            continue
                        target = media / audio.name
                        shutil.copyfile(audio, target)
                        body = {**events[source['id']], 'text': '', 'transcript': None,
                                'attachments': [{'kind': 'audio', 'name': target.name,
                                                 'url': '/media/files/' + target.name, 'media_type': 'audio/wav'}]}
                        event = models.InboundEvent.model_validate(body)
                        start = time.monotonic()
                        transcribed = voice.transcribe(event)
                        facts = extract.extract(transcribed)
                        measured['rows'].append({'id': source['id'], 'added_snr_db': level,
                            'source_noise_snr_db': source['noise_snr_db'], 'audio_sha256': digest,
                            'source_text': source['text'], 'transcript': transcribed.transcript or '',
                            'facts': [fact.model_dump(mode='json') for fact in facts],
                            'when': datetime.now(timezone.utc).isoformat(), 'elapsed_s': time.monotonic() - start})
                        save(path, measured)
                        print(f"{source['id']} {level}: measured, {len(facts)} facts, {time.monotonic() - start:.2f}s", flush=True)
            finally:
                if storage._store is not None:
                    storage._store._db.close()
                    storage._store = None
    finally:
        voice._post, llm._attempt = post_voice, attempt_llm
    return measured


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--resume', action='store_true', help='retain measured clips with identical audio, model and implementation')
    parser.add_argument('--estimate', action='store_true')
    parser.add_argument('--only', action='append', choices=('e02', 'e06', 'e34', 'e41', 'e51', 'e53'))
    parser.add_argument('--levels', nargs='+', type=int, choices=LEVELS, default=list(LEVELS))
    args = parser.parse_args()
    if args.estimate:
        estimate()
        return 0
    measured = live(args) if args.live else json.loads((HERE / 'measurements.json').read_text(encoding='utf-8'))
    report = summarize(measured)
    save(HERE / 'report.json', report)
    (HERE / 'report.md').write_text(render(report) + '\n', encoding='utf-8')
    print(json.dumps({'complete': report['complete'], 'levels': report['levels'],
                      'first_failing_added_snr_db': report['first_failing_added_snr_db']}, indent=2))
    return 0 if report['complete'] and all(row['passed'] or row['safe_failure'] for row in report['results']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
