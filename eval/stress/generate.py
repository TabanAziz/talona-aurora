"""Rewrite every message of the detection cases in five messy styles, once, with the real model.

    uv run --directory backend python ../eval/stress/generate.py --live

Writes `eval/stress/variants.json`. The expected flags never reach a prompt: this script only reads the
`messages` library of `eval/pipeline/cases.json`, never its cases. A variant that loses a unit, sheet, revision,
count or day of its original is dropped and recorded with the reason, so a messy wording can only make detection
harder, never change a fact.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

STYLES = {
    "site_slang": "the way crew members talk on site: slang, abbreviations and short sentences",
    "typos": ("with realistic typos and missing letters in the same language as the original (English), as a "
              "foreman types fast on a phone"),
    "mixed_language": "mixing German and English in the same message, as a bilingual foreman writes it",
    "asr": ("as a speech-to-text transcript: no punctuation at all, all lowercase, as the transcription would "
            "deliver it"),
    "long": "as a long message with small talk around the fact: greetings, the weather, thanks, the weekend",
}

SYSTEM = """You rewrite one message from a construction site in a different style.
Keep every unit, sheet number, revision, count, quantity, date and day word exactly as the original states it.
Change only the wording, never the facts: add nothing and leave nothing out.
Answer with JSON only: {"text": "the rewritten message"}."""

SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}

UNIT = re.compile(r"\b\d+[A-Z]\b")
SHEET = re.compile(r"\b[A-Z]-\d{3}\b")
REVISION = re.compile(r"\brev(?:ision)?\.?\s*([A-Z])\b", re.I)
COUNT = re.compile(r"\b\d+\b")
DAY = re.compile(r"\b(today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend)\b", re.I)


def tokens(text: str) -> dict[str, set[str]]:
    """The facts a rewrite may not lose. Days may be abbreviated ("Fri" for "Friday"), everything else stays exact."""
    return {
        "unit": {match.upper() for match in UNIT.findall(text)},
        "sheet": {match.upper() for match in SHEET.findall(text)},
        "revision": {match.upper() for match in REVISION.findall(text)},
        "count": set(COUNT.findall(text)),
        "day": {match.lower() for match in DAY.findall(text)},
    }


def lost(original: str, variant: str) -> list[str]:
    """What the rewrite dropped, named for the dropped entry. An empty list means the variant may be used."""
    before, after = tokens(original), tokens(variant)
    lowered = variant.lower()
    missing = [f"{kind} {value}" for kind, values in before.items() for value in values
               if kind == "day" and value.lower() not in lowered and value.lower()[:3] not in lowered]
    for kind in ("unit", "sheet", "revision", "count"):
        missing += [f"{kind} {value}" for value in before[kind] if value not in after[kind]]
    return missing


def main(argv: list[str]) -> int:
    from app.core import config, llm

    config.load_dotenv()
    if "--live" not in argv:
        sys.exit("generate.py: pass --live; this writes the committed variants.json once with the real model")
    os.environ["USE_MOCK_LLM"] = "false"
    os.environ.pop("LLM_RECORD", None)
    if not os.environ.get("MISTRAL_API_KEY"):
        sys.exit("generate.py: MISTRAL_API_KEY is not set")

    case_file = json.loads((ROOT / "eval" / "pipeline" / "cases.json").read_text(encoding="utf-8"))
    library = case_file["messages"]
    variants: dict[str, dict[str, str]] = {}
    dropped: list[dict[str, str]] = []
    calls = 0
    for message_id, message in library.items():
        original = message.get("text") or ""
        variants[message_id] = {}
        for style, instruction in STYLES.items():
            user = f"Style: {instruction}\n\nMessage:\n<<<\n{original}\n>>>"
            try:
                answer = llm.complete_json(system=SYSTEM, user=user, schema=SCHEMA)
                calls += 1
            except llm.LLMError as error:
                dropped.append({"message": message_id, "style": style, "reason": f"model: {error}"})
                continue
            text = answer.get("text") if isinstance(answer, dict) else None
            if not isinstance(text, str) or not text.strip():
                dropped.append({"message": message_id, "style": style, "reason": "empty answer"})
                continue
            missing = lost(original, text)
            if missing:
                dropped.append({"message": message_id, "style": style, "reason": "lost " + ", ".join(missing)})
                continue
            variants[message_id][style] = text.strip()
            print(f"ok   {message_id} {style}")

    document = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "model": os.environ.get("LLM_MODEL") or "unknown",
        "styles": STYLES,
        "calls": calls,
        "messages": variants,
        "dropped": dropped,
    }
    (HERE / "variants.json").write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8", newline="\n")
    print(f"generate: {calls} model calls, {sum(len(items) for items in variants.values())} variants kept, "
          f"{len(dropped)} dropped -> {HERE / 'variants.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
