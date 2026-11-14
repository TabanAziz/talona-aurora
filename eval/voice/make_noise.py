"""Build repeatable extra site-noise mixes from the six committed sample recordings."""
import array
import hashlib
import json
import math
import random
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEVELS = (20, 10, 5, 0)
SEED = 9813


def rms(values):
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else 0


def noise(count, rate, seed):
    rng = random.Random(seed)
    return [.7 * rng.uniform(-1, 1) + .3 * (2 * ((i * 173 / rate) % 1) - 1)
            for i in range(count)]


def mix(signal, rate, snr_db, seed):
    generated = noise(len(signal), rate, seed)
    amplitude = rms(signal) / (10 ** (snr_db / 20) * rms(generated))
    added = [sample * amplitude for sample in generated]
    combined = [source + extra for source, extra in zip(signal, added)]
    gain = min(1, 32760 / max(map(abs, combined)))
    # Scale both sources together, preserving the requested ratio without clipping the speech.
    output = array.array('h', [round(sample * gain) for sample in combined])
    return output, {'gain': gain, 'measured_snr_db': 20 * math.log10(rms(signal) / rms(added))}


def read_wave(path):
    with wave.open(str(path), 'rb') as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError('expected 16-bit mono WAV')
        rate = source.getframerate()
        samples = array.array('h', source.readframes(source.getnframes()))
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples, rate


def write_wave(path, samples, rate):
    samples = array.array('h', samples)
    if sys.byteorder != 'little':
        samples.byteswap()
    with wave.open(str(path), 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(samples.tobytes())


def build(destination=HERE / 'clips'):
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'data/voice/manifest.json').read_text(encoding='utf-8'))
    results = []
    for row in manifest:
        source = ROOT / 'data/voice' / row['file']
        samples, rate = read_wave(source)
        for level in LEVELS:
            mixed, info = mix(samples, rate, level, SEED + int(row['id'][1:]))
            target = destination / f"{row['id']}-{level}db.wav"
            write_wave(target, mixed, rate)
            results.append({'id': row['id'], 'added_snr_db': level, 'file': target.name,
                            'source_noise_snr_db': row['noise_snr_db'], 'seconds': len(samples) / rate,
                            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                            'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), **info})
    (destination / 'manifest.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    return results


if __name__ == '__main__':
    clips = build()
    print(f"Built {len(clips)} clips, {sum(row['seconds'] for row in clips):.2f} seconds of audio")
