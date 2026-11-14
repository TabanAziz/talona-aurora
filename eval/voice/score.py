"""Fixed-sample scoring; this rubric never reaches speech or extraction prompts."""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

RUBRIC = {
    'e02': {'unit:3B': r'\b3\s*b\b', 'sheet:A-201': r'\ba\s*-?\s*201\b',
            'revision:B': r'\brev(?:ision)?\.?\s*b\b', 'time:tomorrow': r'\btomorrow\b',
            'time:seven': r'\b7(?:\s*[:.]\s*00)?\b'},
    'e06': {'unit:2A': r'\b2\s*a\b', 'time:this morning': r'\bthis morning\b'},
    'e34': {'time:day after tomorrow': r'\b(?:day after tomorrow|in 2 days)\b',
            'time:seven': r'\b7(?:\s*[:.]\s*00)?\b'},
    'e41': {'unit:2E': r'\b2\s*e\b', 'unit:3B': r'\b3\s*b\b',
            'time:tomorrow': r'\btomorrow\b', 'time:after weekend': r'\bafter (?:the )?weekend\b'},
    'e51': {'unit:2D': r'\b2\s*d\b', 'time:nine': r'\b9(?:\s*[:.]\s*00)?\b'},
    'e53': {'unit:3B': r'\b3\s*b\b', 'sheet:E-201': r'\be\s*-?\s*201\b',
            'revision:A': r'\brev(?:ision)?\.?\s*a\b',
            'time:next working day': r'\bnext (?:working|work|business) day\b'},
}


def normalized_text(text):
    text = re.sub(r'\s+', ' ', text.casefold()).strip()
    for word, digit in {'two': '2', 'three': '3', 'seven': '7', 'nine': '9'}.items():
        text = re.sub(r'\b' + word + r'\b', digit, text)
    return text


def transcript_keys(event_id, text):
    text = normalized_text(text)
    return {key: bool(re.search(pattern, text)) for key, pattern in RUBRIC[event_id].items()}


def semantic_facts(facts):
    # IDs, quote punctuation, subject wording and confidence are presentation/provenance, not fact data.
    return sorted(json.dumps({'type': fact['type'], 'data': fact['data']}, sort_keys=True)
                  for fact in facts)


def rejected(facts):
    return bool(facts) and all(fact.get('data', {}).get('not_understood') is True for fact in facts)


def wrong_critical_values(event_id, facts):
    wrong = {}
    for field in ('unit', 'sheet', 'revision'):
        expected = {key.split(':', 1)[1] for key in RUBRIC[event_id] if key.startswith(field + ':')}
        if not expected:
            continue
        observed = {str(fact['data'][field]).upper() for fact in facts if fact['data'].get(field)}
        if observed - expected:
            wrong[field] = sorted(observed - expected)
    return wrong


def baseline_key_fact_gaps(event_id, facts):
    missing = []
    for field in ('unit', 'sheet', 'revision'):
        expected = {key.split(':', 1)[1] for key in RUBRIC[event_id] if key.startswith(field + ':')}
        observed = {str(fact['data'][field]).upper() for fact in facts if fact['data'].get(field)}
        if field == 'unit':
            observed.update(str(unit).upper() for fact in facts for unit in fact['data'].get('units', []))
        missing.extend(field + ':' + value for value in sorted(expected - observed))
    hour = {'e02': 7, 'e34': 7, 'e51': 9}.get(event_id)
    if hour is not None:
        clocks = []
        for fact in facts:
            for field in ('start', 'time', 'new_time'):
                value = fact['data'].get(field)
                if value:
                    try:
                        clocks.append(datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(ZoneInfo('Europe/Berlin')).hour)
                    except ValueError:
                        pass
        if hour not in clocks:
            missing.append(f'time:{hour:02}:00')
    return missing


def compare(baseline, candidate):
    key_checks = transcript_keys(candidate['id'], candidate['transcript'])
    baseline_gaps = baseline_key_fact_gaps(candidate['id'], baseline['facts'])
    transcript_valid = all(transcript_keys(candidate['id'], baseline['transcript']).values())
    baseline_valid = (transcript_valid
                      and bool(baseline['facts']) and not rejected(baseline['facts'])
                      and not wrong_critical_values(candidate['id'], baseline['facts']) and not baseline_gaps)
    keys_retained = transcript_valid and all(key_checks.values())
    same = (bool(baseline['facts']) and not rejected(baseline['facts'])
            and semantic_facts(baseline['facts']) == semantic_facts(candidate['facts']))
    failed = not keys_retained or not same
    wrong = wrong_critical_values(candidate['id'], candidate['facts'])
    return {'baseline_valid': bool(baseline_valid), 'baseline_transcript_valid': transcript_valid,
            'key_checks': key_checks,
            'baseline_key_fact_gaps': baseline_gaps,
            'keys_retained': bool(keys_retained), 'same_facts': bool(same),
            'passed': bool(baseline_valid and keys_retained and same and not wrong),
            'not_understood': rejected(candidate['facts']),
            'safe_failure': failed and rejected(candidate['facts']),
            'wrong_critical_values': wrong}


def summarize(measurements):
    rows = measurements['rows']
    baselines = {row['id']: row for row in rows if row['added_snr_db'] is None}
    scored = [{**row, **compare(baselines[row['id']], row)} for row in rows if row['added_snr_db'] is not None]
    levels = []
    for level in (20, 10, 5, 0):
        group = [row for row in scored if row['added_snr_db'] == level]
        if group:
            levels.append({'added_snr_db': level, 'n': len(group),
                           'keys_retained': sum(row['keys_retained'] for row in group),
                           'same_facts': sum(row['same_facts'] for row in group),
                           'valid_baselines': sum(row['baseline_valid'] for row in group),
                           'safe_failures': sum(row['safe_failure'] for row in group),
                           'wrong_critical_facts': sum(bool(row['wrong_critical_values']) for row in group),
                           'unrejected_failures': sum(not row['passed'] and not row['not_understood'] for row in group)})
    first = next((level for level in (20, 10, 5, 0)
                  if any(row['added_snr_db'] == level and row['baseline_valid'] and not row['passed']
                         for row in scored)), None)
    first_key_loss = next((level for level in (20, 10, 5, 0)
                           if any(row['added_snr_db'] == level and row['baseline_transcript_valid']
                                  and not row['keys_retained'] for row in scored)), None)
    first_wrong_unit_revision = next((level for level in (20, 10, 5, 0)
                                      if any(row['added_snr_db'] == level and
                                             any(key in row['wrong_critical_values'] for key in ('unit', 'revision'))
                                             for row in scored)), None)
    return {'meta': measurements['meta'], 'complete': len(baselines) == 6 and len(scored) == 24,
            'scope': 'Direct speech-to-extraction measurements without sender read-back. '
                     'The original recognition and extraction errors remain below. '
                     'Separate offline read-back checks use recorded model responses and scripted sender corrections; '
                     'they establish neither improved recognition nor a human phone interaction.',
            'levels': levels, 'first_failing_added_snr_db': first, 'baselines': list(baselines.values()),
            'first_key_loss_added_snr_db': first_key_loss,
            'first_wrong_unit_or_revision_added_snr_db': first_wrong_unit_revision,
            'invalid_baseline_ids': [key for key, row in baselines.items()
                                     if not compare(row, row)['baseline_valid']],
            'results': scored,
            'limitations': [
                'Six synthetic voice notes, one observation per level; this is not a field-accuracy estimate.',
                'e34 and e53 already contain site noise at 8 and 5 dB. Added SNR is relative to each supplied recording.',
                'Key scoring uses the published fixed-sample spelling/time rubric; unfamiliar paraphrases can fail it.',
                'Same facts means identical fact type and data, excluding IDs, quotes, subjects and confidence. Semantic paraphrases of note data can fail it.',
                'Baseline checks require stated unit/sheet/revision values and explicit clock hours in extracted facts. Other semantics and inferred calendar dates are not independently gold-labelled; same facts is stability, not gold accuracy.',
                'A fact accepted from a transcription that loses a key is reported, never replaced or suppressed by this evaluator.',
            ]}
