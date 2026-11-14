"""Generate the synthetic Maple Court project: project.json and schedule.xlsx.

Everything here is fictional demo data. The output is a pure function of SEED and the tables below:
no clock, no global random state, so two runs write identical files.

    python data/project/generate.py            write both files next to this script
    python data/project/generate.py --check    fail when the committed files differ from a fresh run

The ids, names and dates of the demo scenario (mocks/scenario.json) are kept: test_project_data.py
compares them. Expected answers for evaluation do not belong here, they live in /eval.
"""
import hashlib
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from xlsx import write_xlsx

HERE = Path(__file__).resolve().parent
SEED = 20261113
LABEL = "Synthetic demo data. Maple Court is a fictional project."

# The demo day: the schedule is shown as it stands before the first scenario event.
AS_OF = "2026-11-13T06:00:00Z"
HANDOVER = "2026-12-18T16:00:00Z"
CREWS = [
    # name, trade, foreman, people
    ("Framing crew", "Wood framing", "Marco Ruiz", 6),
    ("Electrical crew", "Electrical", "Hannah Kowalski", 4),
    ("Concrete crew", "Concrete and podium", "Dmitri Volkov", 8),
    ("Site labor", "General site labor", "Sam Okafor", 5),
    ("Roofing crew", "Roofing", "Jonas Meyer", 6),
    ("Drywall crew", "Drywall and finishing", "Priya Shah", 6),
]
CONTACTS = [
    {"name": "Dana Whitfield", "role": "Architect", "organisation": "Whitfield Architects (fictional)"},
    {"name": "Lena Ortiz", "role": "Crane operator", "organisation": "Northline Crane Hire (fictional)"},
    {"name": "Ridgeline Concrete dispatch", "role": "Supplier", "organisation": "Ridgeline Concrete (fictional)"},
    {"name": "Plumbing inspector", "role": "Inspector", "organisation": "City building department (fictional)"},
    {"name": "Superintendent", "role": "Superintendent", "organisation": "General contractor"},
]

LEVELS = (1, 2, 3)
LETTERS = "ABCDEFGH"
UNITS = [f"{level}{letter}" for level in LEVELS for letter in LETTERS]

# Framing day per unit (one working day each). Hand-set so that 1C, 2A, 2B and 3B land where
# the demo scenario needs them; the chain after framing is derived below.
FRAME_DAY = {
    "1A": "2026-10-26", "1B": "2026-10-28", "1D": "2026-10-30", "1E": "2026-11-02",
    "1F": "2026-11-03", "1G": "2026-11-04", "1C": "2026-11-05", "1H": "2026-11-06",
    "2C": "2026-11-09", "2A": "2026-11-10", "2D": "2026-11-11", "2B": "2026-11-12",
    "3B": "2026-11-13", "2E": "2026-11-16", "2F": "2026-11-17", "2G": "2026-11-18",
    "2H": "2026-11-19", "3A": "2026-11-20", "3C": "2026-11-23", "3D": "2026-11-24",
    "3E": "2026-11-25", "3F": "2026-11-26", "3G": "2026-11-27", "3H": "2026-11-30",
}
STEPS = ("Frame partitions", "Rough electrical", "Close walls", "Tape and finish")
STEP_CREW = ("Framing crew", "Electrical crew", "Drywall crew", "Drywall crew")

# Task ids the demo scenario already uses.
SCENARIO_ID = {("3B", 0): "T-031", ("3B", 1): "T-032", ("2A", 2): "T-060", ("1C", 2): "T-061"}
# The scenario's two wall-closing tasks have no predecessor, and 1C waits for a free drywall crew.
NO_DEPENDENCIES = {"T-060", "T-061"}
CLOSE_DAY_OVERRIDE = {"1C": "2026-11-13"}

# Rough plumbing inspections that deviate from "the working day after electrical, at a seeded hour".
INSPECTION_OVERRIDE = {
    "1C": {"at": "2026-11-09T13:00:00Z", "status": "passed", "signed_off_at": "2026-11-09T15:20:00Z"},
    "2A": {"at": "2026-11-12T13:00:00Z", "status": "scheduled", "signed_off_at": None},
}

# The roof chain after the sheathing runs back to back, so a one-day slip of the crane moves the
# handover by one working day. Tape and finish work has slack and does not.
ROOF_CHAIN = [
    ("T-070", "Roof underlayment and flashing", "Roofing crew", 3),
    ("T-071", "Roof membrane and curbs", "Roofing crew", 4),
    ("T-072", "Rooftop equipment set", "Roofing crew", 2),
    ("T-073", "Roof leak test", "Site labor", 1),
    ("T-074", "Level 3 ceiling and roof-line finishes", "Drywall crew", 5),
    ("T-075", "Corridor and stair finishes", "Site labor", 4),
    ("T-076", "Punch list", "Site labor", 2),
    ("T-077", "Final clean", "Site labor", 1),
    ("T-078", "Final inspection and handover", "Site labor", 1),
]

FIXED_TASKS = [
    ("T-040", "Podium topping pour", None, "Concrete crew", "2026-11-13T06:00:00Z", "2026-11-13T09:00:00Z", [], None),
    ("T-041", "Curing protection", None, "Site labor", "2026-11-13T09:00:00Z", "2026-11-13T11:00:00Z", ["T-040"], None),
    ("T-050", "Roof truss lift", None, "Roofing crew", "2026-11-13T07:00:00Z", "2026-11-13T15:00:00Z", [], None),
    ("T-051", "Roof sheathing", None, "Roofing crew", "2026-11-16T07:00:00Z", "2026-11-17T15:00:00Z", ["T-050"], None),
]

def task_id(unit: str, step: int) -> str:
    if (unit, step) in SCENARIO_ID:
        return SCENARIO_ID[(unit, step)]
    return f"T-{100 + UNITS.index(unit) * 10 + step}"


# The last field names the task a line serves. The contract's ResourceLine carries no task, so
# this link is project data: without it nobody can tell which task a late truck or crane affects.
FIXED_RESOURCES = [
    ("R-trucks", "Concrete trucks", "delivery", "2026-11-13T06:00:00Z", 3, "trucks", "T-040"),
    ("R-crane", "Mobile crane", "equipment", "2026-11-13T07:00:00Z", 1, "count", "T-050"),
    ("R-framing", "Framing crew", "crew", "2026-11-13T06:00:00Z", 6, "people", "T-031"),
    ("R-electrical", "Electrical crew", "crew", "2026-11-13T06:00:00Z", 4, "people", None),
    ("R-concrete", "Concrete crew", "crew", "2026-11-13T06:00:00Z", 8, "people", "T-040"),
    ("R-roofing", "Roofing crew", "crew", "2026-11-13T07:00:00Z", 6, "people", "T-050"),
    ("R-drywall", "Drywall crew", "crew", "2026-11-13T07:00:00Z", 6, "people", None),
    ("R-lift", "Scissor lift", "equipment", "2026-11-16T06:00:00Z", 2, "count", None),
    ("R-drywall-l3", "Drywall board level 3", "delivery", "2026-11-16T07:00:00Z", 420, "sheets", task_id("3A", 2)),
    ("R-lumber-l3", "Framing lumber level 3", "delivery", "2026-11-18T06:00:00Z", 5, "loads", task_id("3A", 0)),
    ("R-underlayment", "Roofing underlayment", "delivery", "2026-11-18T07:00:00Z", 40, "rolls", "T-070"),
]


def pick(key: str, options: list):
    """Deterministic choice that does not depend on the Python version's random module."""
    digest = hashlib.sha256(f"{SEED}:{key}".encode()).digest()
    return options[int.from_bytes(digest[:4], "big") % len(options)]


def iso(day: date, hour: int, minute: int = 0) -> str:
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}:00Z"


def add_working_days(day: date, count: int) -> date:
    while count > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


def day_of(text: str) -> date:
    return date.fromisoformat(text)


def build_tasks() -> list[dict]:
    cutoff = datetime.fromisoformat(AS_OF.replace("Z", "+00:00")).date()
    tasks: dict[str, dict] = {}

    for unit in UNITS:
        frame = day_of(FRAME_DAY[unit])
        electrical = add_working_days(frame, 1)
        inspection = add_working_days(electrical, 1)
        close = day_of(CLOSE_DAY_OVERRIDE[unit]) if unit in CLOSE_DAY_OVERRIDE else add_working_days(inspection, 1)
        tape = add_working_days(close, 1)
        spans = [
            (iso(frame, 6), iso(frame, 14)),
            (iso(electrical, 6), iso(electrical, 14)),
            (iso(close, 7), iso(close, 15)),
            (iso(tape, 7), iso(add_working_days(tape, 1), 15)),
        ]
        for step, (start, end) in enumerate(spans):
            tid = task_id(unit, step)
            depends = [] if step == 0 or tid in NO_DEPENDENCIES else [task_id(unit, step - 1)]
            tasks[tid] = {
                "id": tid,
                "name": f"{STEPS[step]} {unit}",
                "unit": unit,
                "crew": STEP_CREW[step],
                "start": start,
                "end": end,
                "depends_on": depends,
                "requires_inspection": f"Rough plumbing {unit}" if step == 2 else None,
                "status": "done" if day_of(end[:10]) < cutoff else "planned",
            }

    for tid, name, unit, crew, start, end, depends, inspection in FIXED_TASKS:
        tasks[tid] = {
            "id": tid, "name": name, "unit": unit, "crew": crew, "start": start, "end": end,
            "depends_on": depends, "requires_inspection": inspection, "status": "planned",
        }

    previous, day = "T-051", day_of("2026-11-17")
    for tid, name, crew, days in ROOF_CHAIN:
        first = add_working_days(day, 1)
        last = add_working_days(first, days - 1)
        depends = [previous]
        if tid == "T-075":
            depends += [task_id(u, 3) for u in UNITS if u.startswith("3")]
        end_hour = 16 if tid == "T-078" else 15
        tasks[tid] = {
            "id": tid, "name": name, "unit": None, "crew": crew,
            "start": iso(first, 8 if tid == "T-078" else 7), "end": iso(last, end_hour),
            "depends_on": depends, "requires_inspection": None, "status": "planned",
        }
        previous, day = tid, last

    return sorted(tasks.values(), key=lambda t: (t["start"], t["id"]))


def build_inspections() -> list[dict]:
    out = []
    cutoff = AS_OF[:10]
    for unit in UNITS:
        electrical = add_working_days(day_of(FRAME_DAY[unit]), 1)
        day = add_working_days(electrical, 1)
        override = INSPECTION_OVERRIDE.get(unit)
        if override:
            at, status, signed = override["at"], override["status"], override["signed_off_at"]
        else:
            at = iso(day, pick(f"inspection-hour:{unit}", [9, 10, 13, 14]))
            if at[:10] < cutoff:
                status = "passed"
                signed = iso(day, int(at[11:13]) + 2, 0)
            else:
                status, signed = "scheduled", None
        out.append({
            "id": f"INS-{unit}-RP",
            "name": f"Rough plumbing {unit}",
            "unit": unit,
            "inspector": "Plumbing inspector",
            "scheduled_at": at,
            "status": status,
            "signed_off_at": signed,
        })
    return out


def build_resources() -> list[dict]:
    return [
        {"id": rid, "item": item, "kind": kind, "date": at, "planned": planned, "actual": None, "unit": unit,
         "task": task}
        for rid, item, kind, at, planned, unit, task in FIXED_RESOURCES
    ]


def build_units() -> list[dict]:
    kinds = [("Studio", 32), ("1 bed", 46), ("2 bed", 68)]
    out = []
    for unit in UNITS:
        kind, area = pick(f"unit-type:{unit}", kinds)
        out.append({"id": unit, "level": int(unit[0]), "type": kind, "area_m2": area})
    return out


def build_project() -> dict:
    return {
        "demo_data": True,
        "label": LABEL,
        "seed": SEED,
        "as_of": AS_OF,
        "handover": HANDOVER,
        "calendar": {"working_days": "Mon-Fri", "holidays": [], "timezone": "UTC"},
        "project": {
            "id": "maple-court",
            "name": "Maple Court",
            "description": "24-unit multifamily building, wood frame over podium",
            "units": UNITS,
            "sheets": ["A-201"],
            "crews": [c[0] for c in CREWS],
            "demo_data": True,
        },
        "units": build_units(),
        "crews": [{"name": n, "trade": t, "foreman": f, "people": p} for n, t, f, p in CREWS],
        "contacts": CONTACTS,
        "inspections": build_inspections(),
        "resources": build_resources(),
    }


TASK_COLUMNS = ["Task ID", "Task name", "Unit", "Crew", "Start", "Finish", "Predecessors", "Requires inspection", "Status"]
RESOURCE_COLUMNS = ["Resource ID", "Item", "Kind", "Date", "Planned", "Actual", "Unit of measure", "Task"]
INSPECTION_COLUMNS = ["Inspection ID", "Inspection", "Unit", "Inspector", "Scheduled", "Status", "Signed off"]


def build_workbook() -> list:
    tasks = build_tasks()
    return [
        ("Info", [
            ["Field", "Value"],
            ["Project", "Maple Court"],
            ["Label", LABEL],
            ["As of", AS_OF],
            ["Handover", HANDOVER],
            ["Working days", "Mon-Fri, no holidays"],
        ]),
        ("Schedule", [TASK_COLUMNS] + [
            [t["id"], t["name"], t["unit"], t["crew"], t["start"], t["end"], ", ".join(t["depends_on"]),
             t["requires_inspection"], t["status"]]
            for t in tasks
        ]),
        ("Resources", [RESOURCE_COLUMNS] + [
            [r["id"], r["item"], r["kind"], r["date"], r["planned"], r["actual"], r["unit"], r["task"]]
            for r in build_resources()
        ]),
        ("Inspections", [INSPECTION_COLUMNS] + [
            [i["id"], i["name"], i["unit"], i["inspector"], i["scheduled_at"], i["status"], i["signed_off_at"]]
            for i in build_inspections()
        ]),
    ]


def render_project_json() -> bytes:
    return (json.dumps(build_project(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def main(argv: list[str]) -> int:
    json_path, xlsx_path = HERE / "project.json", HERE / "schedule.xlsx"
    if "--check" in argv:
        scratch = HERE / ".schedule.check.xlsx"
        try:
            write_xlsx(scratch, build_workbook())
            same = (
                json_path.read_bytes() == render_project_json()
                and xlsx_path.read_bytes() == scratch.read_bytes()
            )
        finally:
            scratch.unlink(missing_ok=True)
        print("up to date" if same else "committed files differ from a fresh run: run generate.py")
        return 0 if same else 1
    with open(json_path, "wb") as fh:
        fh.write(render_project_json())
    write_xlsx(xlsx_path, build_workbook())
    print(f"wrote {json_path.name} and {xlsx_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
