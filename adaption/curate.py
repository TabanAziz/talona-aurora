"""Curate the Adaption-generated rows into history.json: routine Maple Court messages before the demo events.

    uv run --directory backend python ../adaption/curate.py
    uv run --directory backend python ../adaption/curate.py --dry   print the rows, write nothing

Adaption generated site messages for other projects, in other channels and with other senders. This maps each
row back onto Maple Court: the site name, the units, the levels and the sheet come from data/project, the sender
is the project's own foreman for the trade the generated sender names, and only sentences about routine building
work survive, so the history raises no flag in the rules. Where a message names no unit, its chat label names
one. Every crew gets at least three messages. Days become offsets from the demo anchor on the days before the
first scenario event. The sentences stay the generated ones; nothing is written by hand.
"""
import json
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

import rows

HERE = Path(__file__).resolve().parent
GENERATED = HERE / "generated.jsonl"
HISTORY = HERE / "history.json"
# All before the first scenario event (day -9), so the history reads as what happened on site last week.
START_DAY = -14
SPAN = 5
MIN_TEXT = 12
MIN_PER_CREW = 3
# The demo's drawing change is about 3B: work reported there before it would open a rework case the demo does
# not expect, so the history leaves that unit alone.
RESERVED_UNITS = {"3B"}

PROMPT = re.compile(
    r"Channel:\s*(?P<channel>[^.]*)\.\s*From:\s*(?P<sender>.*?)\.\s*Day:\s*(?P<day>[+-]?\d+)\.\s*"
    r"Time:\s*(?P<time>\d{1,2}:\d{2})\.",
    re.IGNORECASE,
)
SITE_NAME = re.compile(r"^(?P<site>.+?)\s+site message\b", re.IGNORECASE)
SUBJECT = re.compile(r"\s*Subject:\s*(?P<subject>.+?)(?:\.\s|\s*$)", re.IGNORECASE)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
DAYS = re.compile(
    r"\bDay\s+\d+\b|\bon\s+day\s+\w+\b|\bday\s+"
    r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen"
    r"|seventeen|eighteen|nineteen|twenty)\b",
    re.IGNORECASE,
)
# Only work on the building: the generated set also holds software, museum and game rows.
TOPIC = re.compile(
    r"\b(framing|frame|walls?|slab|concrete|pouring|poured|rebar|formwork|foundations?|footings?|excavation"
    r"|trench\w*|grading|electrical|wiring|panels?|conduit|plumbing|pipes?|drains?|ductwork|ducts?|hvac|roofing"
    r"|roof|flashing|shingles?|glazing|facade|cladding|drywall|painting|paint|primer|til(e|es|ing)|flooring"
    r"|insulation|skylights?|lighting|fixtures?|waste removal|cleaning|sweeping|patrol|lumber|steel|beams?"
    r"|columns?|scaffolding|windows?|doors?|masonry|paving)\b",
    re.IGNORECASE,
)
OFFTOPIC = re.compile(
    r"\b(assets?|gltf|lowpoly|textur\w*|render\w*|virtual|archiv\w*|modeling|animat\w*|dissect\w*|anatom\w*|mars"
    r"|habitat|oxygen|simulator|chronometer|potsdam|athens|unesco|rails?|runway|hangar|naval|hull|dredg\w*|statue"
    r"|museum|exhibits?|gallery|historic|heritage|vintage|film|audio|speakers?|video|game|servers?|pipeline|data"
    r"|crypto|eagle|biolo\w*|art\b|thatch\w*|bag end|london|vancouver|patient|spire|cathedral|artifacts?"
    r"|acoustic|sculptur\w*|painting pass|wall coverings)\b",
    re.IGNORECASE,
)
# A routine message states progress and nothing else: no drawing, no inspection, no delay, no ask.
NOISE = re.compile(
    r"\b(rev(ision)?s?|dwg|drawing[s]?|sheet|rfi|submittal|specs?|specification[s]?|change order|cor)\b"
    r"|\b(inspect\w*|punch|permit|clash\w*|delay\w*|approv\w*|coordinat\w*|verif\w*|fail\w*|stop work|hold\b"
    r"|unsafe|safety|incident|variance|non-compliant|deficien\w*|defect\w*|shoring|hazard\w*|asbestos|claim"
    r"|warranty|backcharge|shortage|blocking|stalled)\b"
    r"|\b(deliver\w*|truck\w*|crane|shipment|dispatch\w*|supplier)\b"
    r"|\b(clos(e|es|ed|ing|ure)|drywall\w*|board(s|ing)?|insulat\w*|sheath\w*|ceiling[s]?|backfill\w*"
    r"|cover(s|ed|ing)?|tap(e|ing)|hang(s|ing)?)\b"
    r"|\b(blocked|conflict\w*|halt\w*|paus\w*|borderline|deviation\w*|discrepanc\w*|missing|broken|wrong"
    r"|rework|damage\w*|leak\w*|crack\w*|sag\w*|issues?|problem\w*|risk\w*|concern\w*|overrun|correction)\b"
    r"|\b(must|shall|need|needs|please|should|ensure|await\w*|recalibrat\w*)\b"
    r"|\bfor (have|has|is|are|will|was)\b|\bscheduled\b|\b(arriving|arrives)\b|\bwith testing\b",
    re.IGNORECASE,
)
# Messages from site also carry instructions; the history keeps the statements of what happened.
IMPERATIVE = re.compile(
    r"^(install|submit|verify|recalibrate|review|check|replace|confirm|send|provide|coordinate|ensure|fix|apply|use"
    r"|keep|clear|stop|do|put|bring|avoid|inspect|schedule|reschedule|order|deliver|remove|reinforce|redo|rework"
    r"|cover|close|open|start|finish|hold|test|call|email|notify|update|escalate|advise|add|run|bend|cut|pour|lay"
    r"|erect|tape|hang|paint|clean|secure|expect|plan|note|remember|double|report|remind|allow|remain)\b",
    re.IGNORECASE,
)
# A statement about work that happened or is in progress, as opposed to an ask or an opinion.
STATEMENT = re.compile(
    r"\b(is|are|was|were|has|have|had|completed?|finish\w*|start\w*|pass\w*|arriv\w*|install\w*|clear\w*|done"
    r"|ready|placed|poured|laid|erected|begun|began|continue[sd]?|remain[sd]?|hold[s]?|held|running|moving|stacked"
    r"|stored|tested|progress\w*|mobiliz\w*|work\w*|on site|in place|online|operational|underway)\b",
    re.IGNORECASE,
)
UNIT_PHRASE = re.compile(r"\bUnits?\s+[A-Z]?\d{1,3}[A-Z]?(?:\s*(?:-|through|to|and)\s*[A-Z]?\d{1,3}[A-Z]?)?\b",
                         re.IGNORECASE)
SHEET = re.compile(r"\b[A-Z]{1,3}-\d{2,4}\b")
LEVEL = re.compile(
    r"\b(?:levels?|floors?)\s+(?P<digit>[0-9]+)\b"
    r"|\b(?:levels?|floors?)\s+(?P<word>one|two|three|four|five|six|seven|eight|nine|ten)\b"
    r"|\b(?P<ordinal>first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+(?:floor|level)\b",
    re.IGNORECASE,
)
LEVEL_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
               "nine": 9, "ten": 10, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
               "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
# The trade a generated sender names, so the message comes from the foreman of that trade.
TRADE = [
    ("Schedule update", r"schedule|planner|planning|coordinator|automated|\bsystem\b|\bbot\b"),
    ("Lena Ortiz", r"crane|rigging|lift tech|barge|captain|hoist"),
    ("Plumbing inspector", r"inspector|quality control|\bqc\b|surveyor|auditor"),
    ("Ridgeline Concrete dispatch", r"supplier|batching|dispatch|materials"),
    ("Superintendent", r"superintendent|site manager|\bmanager\b|\bhse\b|safety|security"),
    ("Dana Whitfield", r"architect|design\w*|consultant|engineer|\bspec\b|spec\.|curator|acoustic|owner"),
    ("Hannah Kowalski", r"electric\w*|lighting|solar|\bpv\b|power|\bav\b"),
    ("Jonas Meyer", r"roof\w*|flashing|shingle|skylight"),
    ("Dmitri Volkov", r"concrete|slab|pour|formwork|rebar|foundation|pil\w+|excavat\w*|grading|earthwork|dredg\w*"),
    ("Marco Ruiz", r"framing|frame|carpent\w*|timber|steel|structural|erection|welding|weld"),
    ("Priya Shah", r"drywall|interior|finish\w*|paint\w*|til\w+|plaster\w*|flooring|insulat\w*|glaz\w*|cladding"
                   r"|facade|plumbing|hvac|mechanical|elevator|tiling"),
    ("Sam Okafor", r"labor|labour|site|general|clean|waste|logistics|civil|tech|foreman"),
]


def parse(item: dict) -> dict | None:
    """The site, channel, sender, day and time a generated prompt names, with the subject when it has one."""
    prompt = item.get("original_prompt") or ""
    match = PROMPT.search(prompt)
    if not match:
        return None
    hours, minutes = (int(part) for part in match["time"].split(":"))
    if hours > 23 or minutes > 59 or match["day"].startswith("-"):
        return None
    subject = SUBJECT.search(prompt[match.end():])
    site = SITE_NAME.search(prompt)
    return {
        "site": site["site"].strip() if site else "Maple Court",
        "channel": match["channel"].strip().lower(),
        "sender": match["sender"].strip(),
        "day": int(match["day"]),
        "time": f"{hours:02d}:{minutes:02d}",
        "subject": subject["subject"].strip() if subject else None,
    }


def keep(sentence: str) -> bool:
    return (len(sentence) >= MIN_TEXT and not NOISE.search(sentence) and "?" not in sentence
            and not IMPERATIVE.search(sentence) and STATEMENT.search(sentence) is not None
            and TOPIC.search(sentence) is not None and OFFTOPIC.search(sentence) is None
            and not re.search(r"\b(for|with|to|at|in|on|the|and)$", sentence, re.IGNORECASE))


def routine(text: str) -> str:
    """The sentences of a message that only state routine building work, joined again."""
    text = re.sub(r"\s+", " ", DAYS.sub(" ", text or "")).strip()
    kept = [s.strip(" .;") for s in SENTENCE_SPLIT.split(text.strip()) if s.strip()]
    return " ".join(s + "." for s in kept if keep(s))


def level_of(text: str) -> int | None:
    match = LEVEL.search(text)
    if not match:
        return None
    value = match.group("digit") or match.group("word") or match.group("ordinal")
    if value is None:
        return None
    number = int(value) if value.isdigit() else LEVEL_WORDS.get(value.lower(), 1)
    return max(1, min(3, number))


def for_project(text: str, site: str, unit: str, level: int) -> str:
    """The generated text with every site name, unit, level and sheet replaced by a Maple Court one."""
    text = re.sub(re.escape(site), "Maple Court", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*){0,2}\s+site message\b", "Maple Court", text)
    text = UNIT_PHRASE.sub(f"Unit {unit}", text)
    text = LEVEL.sub(f"Level {level}", text)
    text = SHEET.sub("A-201", text)
    for dash in ("\u2014", "\u2013"):
        text = text.replace(dash, "-")
    text = re.sub(r"\bthe Level\b", "Level", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;:")
    return re.sub(r"^[,;:]\s*", "", text)


def sender_for(hint: str) -> str | None:
    """The project sender the generated sender names, or None when it names no role the project has."""
    for name, pattern in TRADE:
        if re.search(pattern, hint, re.IGNORECASE):
            return name
    return None


def curate(items: list[dict], known: dict) -> list[dict]:
    candidates = []
    for item in items:
        fields = parse(item)
        text = routine(item.get("enhanced_completion") or "")
        if not fields or len(text) < MIN_TEXT:
            continue
        candidates.append({**fields, "text": text})
    candidates.sort(key=lambda row: (row["day"], row["time"], row["text"]))
    seen = set()
    unique = []
    for row in candidates:
        key = re.sub(r"\W+", " ", row["text"].lower()).strip()
        if key not in seen:
            seen.add(key)
            unique.append(row)

    units = [u for u in known["units"] if u not in RESERVED_UNITS]
    by_level = {level: [u for u in units if u.startswith(str(level))] for level in (1, 2, 3)}
    senders = known["senders"]
    rows_out = []
    for index, row in enumerate(unique):
        digest = int(hashlib.sha256(row["text"].encode()).hexdigest(), 16)
        level = level_of(row["text"]) or 1 + digest % 3
        candidates_units = by_level[level]
        unit = candidates_units[digest % len(candidates_units)]
        text = for_project(row["text"], row["site"], unit, level)
        if not UNIT_PHRASE.search(row["text"]):
            text = f"{unit}: {text}"
        sender = sender_for(f"{row['sender']}, {row['channel']}")
        rows_out.append({"time": row["time"], "subject": row["subject"], "sender": sender,
                         "channel": channel_for(sender, senders) if sender else None, "text": text,
                         "day": START_DAY + row["day"] % SPAN})
    fill(rows_out, known)
    return rows_out


def channel_for(sender: str | None, senders: dict) -> str | None:
    if sender is None:
        return None
    if sender == "Schedule update":
        return "schedule"
    return "email" if senders[sender]["crew"] is None else "telegram"


def fill(rows_out: list[dict], known: dict) -> None:
    """Give the rows with no trade a sender: a crew short of three messages first, then the schedule system."""
    senders = known["senders"]
    crew_of = {sender["crew"]: name for name, sender in senders.items() if sender["crew"]}
    counts = Counter(senders[row["sender"]]["crew"] for row in rows_out
                     if row["sender"] and senders[row["sender"]]["crew"])
    for row in rows_out:
        if row["sender"] is not None:
            continue
        short = next((crew for crew in known["crews"] if counts[crew] < MIN_PER_CREW), None)
        row["sender"] = crew_of[short] if short else "Schedule update"
        row["channel"] = channel_for(row["sender"], senders)
        if short:
            counts[short] += 1
    for row in rows_out:
        row["sender_role"] = senders[row["sender"]]["role"]


def place(history: list[dict]) -> None:
    """Give every row its id and, for email, a subject; the day offset came from the generated day already."""
    history.sort(key=lambda row: (row["day"], row["time"], row["text"]))
    for index, row in enumerate(history):
        row["id"] = f"h{index + 1:02d}"
        if row["channel"] == "email" and not row["subject"]:
            row["subject"] = " ".join(row["text"].split()[:8]).rstrip(",.;") or "Site update"


def main(argv: list[str]) -> int:
    known = rows.project()
    history = curate(rows.read_jsonl(GENERATED), known)
    place(history)
    for row in list(history):
        problems = rows.problems(row, known)
        if problems:
            history.remove(row)
            print(f"SKIP {row['id']}: {'; '.join(problems)}")
    per_crew = Counter(known["senders"][row["sender"]]["crew"] for row in history
                       if known["senders"][row["sender"]]["crew"])
    named = {u for row in history for u in rows.refs(row, known)["units"]}
    print(f"rows: {len(history)}, channels: {dict(Counter(row['channel'] for row in history))}")
    print(f"messages per crew: {dict(sorted(per_crew.items()))}")
    print(f"units named: {len(named)} ({', '.join(sorted(named))})")
    print(f"days: {sorted({row['day'] for row in history})}")
    if "--dry" in argv:
        for row in history:
            print(f"  {row['id']} d{row['day']} {row['time']} {row['channel']:7s} {row['sender']:26s} {row['text'][:110]}")
        return 0
    HISTORY.write_text(json.dumps({"anchor_day": rows.ANCHOR_DAY.isoformat(), "rows": history}, indent=2) + "\n",
                       encoding="utf-8", newline="\n")
    print(f"wrote {HISTORY.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
