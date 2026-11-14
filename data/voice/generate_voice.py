"""Makes the sample voice notes once and writes them as 16 kHz mono WAV files with a manifest.

  python data/voice/generate_voice.py plan          show what would be made, no network
  python data/voice/generate_voice.py voices        list the usable ElevenLabs voices (free, read only)
  python data/voice/generate_voice.py make          generate the missing notes (spends speech credits)
  python data/voice/generate_voice.py make --force  generate all of them again

The audio files are committed, so nothing else ever needs to run this. It is not part of any test run: the
tests only read the committed files. The text of each note comes from data/messages/voice_texts.json. Site
noise is mixed in locally (no model, no credits), so the same speech always gives the same noisy file.
Needs ELEVENLABS_API_KEY in the environment or in the repo's .env. Standard library only.
"""
import array
import hashlib
import json
import math
import os
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RATE = 16000
API = "https://api.elevenlabs.io"
MODEL = "eleven_multilingual_v2"
TIMEOUT_S = 60
PAD_S = 0.3

# Event id, noise (None or the speech to noise ratio in dB). Six notes, two of them with site noise.
NOTES = [
    ("e02", None),
    ("e06", None),
    ("e34", 8),
    ("e41", None),
    ("e51", None),
    ("e53", 5),
]

# Speaker to the start of a premade voice name, so the script finds the voice id itself.
VOICES = {
    "Marco Ruiz": "Chris",
    "Jonas Meyer": "Roger",
    "Priya Shah": "Jessica",
    "Hannah Kowalski": "Sarah",
}


def load_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    env = ROOT / ".env"
    if not key and env.is_file():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ELEVENLABS_API_KEY":
                key = value.strip().strip("'\"")
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY is not set")
    return key


def request(path: str, key: str, body: dict | None = None) -> bytes:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"xi-api-key": key, "Content-Type": "application/json"}
    call = urllib.request.Request(API + path, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(call, timeout=TIMEOUT_S) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"ElevenLabs answered HTTP {error.code} for {path.split('?')[0]}") from None


def list_voices(key: str) -> list[dict]:
    return json.loads(request("/v1/voices", key))["voices"]


def find_voice(voices: list[dict], prefix: str) -> dict:
    for voice in voices:
        if voice.get("category") == "premade" and voice["name"].startswith(prefix):
            return voice
    raise SystemExit(f"no premade voice starting with {prefix!r}")


def speak(text: str, voice_id: str, key: str) -> array.array:
    path = f"/v1/text-to-speech/{urllib.parse.quote(voice_id)}?output_format=pcm_{RATE}"
    audio = request(path, key, {"text": text, "model_id": MODEL})
    samples = array.array("h")
    samples.frombytes(audio[: len(audio) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def rms(samples) -> float:
    return math.sqrt(sum(s * s for s in samples) / len(samples)) if len(samples) else 0.0


def site_noise(count: int, seed: int) -> list[float]:
    """Engine hum, rumble, hiss and hammer hits, scaled to a root mean square of 1."""
    rng = random.Random(seed)
    out = []
    low = 0.0
    for i in range(count):
        t = i / RATE
        low += 0.03 * (rng.uniform(-1, 1) - low)
        hum = sum(a * math.sin(2 * math.pi * f * t) for f, a in ((62, 0.5), (124, 0.3), (186, 0.15)))
        out.append(6 * low + hum + 0.15 * rng.uniform(-1, 1))
    position = int(rng.uniform(0.3, 0.9) * RATE)
    while position < count:
        for j in range(min(int(0.09 * RATE), count - position)):
            out[position + j] += 1.8 * rng.uniform(-1, 1) * math.exp(-j / (0.025 * RATE))
        position += int(rng.uniform(1.0, 1.8) * RATE)
    level = math.sqrt(sum(x * x for x in out) / count)
    return [x / level for x in out]


def add_noise(speech: array.array, snr_db: float, seed: int) -> array.array:
    noise = site_noise(len(speech), seed)
    gain = rms(speech) / (10 ** (snr_db / 20))
    mixed = array.array("h")
    for s, n in zip(speech, noise):
        mixed.append(max(-32768, min(32767, int(round(s + n * gain)))))
    return mixed


def pad(speech: array.array) -> array.array:
    gap = array.array("h", [0] * int(PAD_S * RATE))
    return gap + speech + gap


def write_wav(path: Path, samples: array.array) -> None:
    little = array.array("h", samples)
    if sys.byteorder == "big":
        little.byteswap()
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(little.tobytes())


def script_texts() -> dict:
    return json.loads((ROOT / "data" / "messages" / "voice_texts.json").read_text(encoding="utf-8"))


def plan() -> list[dict]:
    texts = script_texts()
    return [{
        "id": event_id, "file": f"{event_id}.wav", "speaker": texts[event_id]["speaker"],
        "text": texts[event_id]["text"], "noise_snr_db": snr,
    } for event_id, snr in NOTES]


def make(force: bool) -> None:
    key = load_key()
    voices = list_voices(key)
    manifest_path = HERE / "manifest.json"
    manifest = {n["id"]: n for n in json.loads(manifest_path.read_text(encoding="utf-8"))} if manifest_path.is_file() else {}
    for item in plan():
        target = HERE / item["file"]
        if target.is_file() and not force:
            print(f"skip {item['file']}, already there")
            continue
        voice = find_voice(voices, VOICES[item["speaker"]])
        speech = speak(item["text"], voice["voice_id"], key)
        if len(speech) < RATE // 2:
            raise SystemExit(f"{item['file']}: the speech service returned almost no audio")
        samples = pad(speech)
        if item["noise_snr_db"] is not None:
            samples = add_noise(samples, item["noise_snr_db"], seed=int(item["id"][1:]))
        write_wav(target, samples)
        manifest[item["id"]] = {
            **item, "voice": voice["name"].split(" - ")[0], "model": MODEL, "seconds": round(len(samples) / RATE, 2),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        print(f"made {item['file']}: {manifest[item['id']]['seconds']} s")
    ordered = [manifest[event_id] for event_id, _ in NOTES if event_id in manifest]
    manifest_path.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "plan"
    if command == "plan":
        for item in plan():
            print(f"{item['file']}: {item['speaker']}, noise {item['noise_snr_db']}: {item['text']}")
        total = sum(len(item["text"]) for item in plan())
        print(f"{total} characters of speech in {len(NOTES)} notes")
    elif command == "voices":
        for voice in list_voices(load_key()):
            print(voice["category"], voice["name"])
    elif command == "make":
        make("--force" in argv)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
