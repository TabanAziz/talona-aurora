"""The demo project, plan and record history, from data/project when it exists, else from mocks/scenario.json.

DEMO_ANCHOR moves every date by whole days so that the scenario's Thursday falls on the anchor day
(`today` or YYYY-MM-DD). Unset, every date stays as generated, which keeps tests and recordings stable.
"""
import importlib.util
import json
import os
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from app.core import config
from app.core import models as m
from app.core import scenario

# The day the scenario's messages lead up to: the evening before the Friday work starts.
SCENARIO_DAY = date(2026, 11, 12)
PROJECT_DIR = config.ROOT / "data" / "project"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_PATTERN = re.compile(r"\b(" + "|".join(WEEKDAYS) + r")\b", re.IGNORECASE)


class DemoDataError(ValueError):
    pass


@dataclass(frozen=True)
class DemoData:
    project: m.Project
    plan: m.Plan
    history: list[m.RecordEntry]
    source: str
    shift_days: int


def load() -> DemoData:
    if config.project_directory.get() is not None:
        seed = json.loads((config.data_dir() / "seed.json").read_text(encoding="utf-8"))
        return DemoData(project=m.Project.model_validate(seed["project"]),
                        plan=m.Plan.model_validate(seed["plan"]), history=[], source="workspace", shift_days=0)
    days = shift_days()
    if (PROJECT_DIR / "project.json").is_file() and (PROJECT_DIR / "schedule.xlsx").is_file():
        project, plan, source = _project_json(), _schedule_xlsx(), "data/project"
    else:
        raw = scenario.load()
        project, plan, source = m.Project.model_validate(raw["project"]), m.Plan.model_validate(raw["plan"]), "mocks"
    # data/project has no message history; the scenario's history is the one that matches the messages.
    history = [m.RecordEntry.model_validate(entry) for entry in scenario.load()["baseline_record"]]
    return DemoData(
        project=project,
        plan=shift_plan(plan, days),
        history=[shift_entry(entry, days) for entry in history],
        source=source,
        shift_days=days,
    )


def shift_days(anchor: str | None = None) -> int:
    value = (os.environ.get("DEMO_ANCHOR", "") if anchor is None else anchor).strip().lower()
    if not value:
        return 0
    if value == "today":
        day = datetime.now(timezone.utc).date()
    else:
        try:
            day = date.fromisoformat(value)
        except ValueError:
            raise DemoDataError(f"DEMO_ANCHOR must be 'today' or YYYY-MM-DD, not {value!r}") from None
    return (day - SCENARIO_DAY).days


def shift_plan(plan: m.Plan, days: int) -> m.Plan:
    if not days:
        return plan
    delta = timedelta(days=days)
    return plan.model_copy(update={
        "tasks": [t.model_copy(update={"start": t.start + delta, "end": t.end + delta}) for t in plan.tasks],
        "resources": [r.model_copy(update={"date": r.date + delta}) for r in plan.resources],
        "handover": plan.handover + delta,
    })


def shift_entry(entry: m.RecordEntry, days: int) -> m.RecordEntry:
    return entry.model_copy(update={"at": entry.at + timedelta(days=days)}) if days else entry


def shift_events(events: Iterable[m.InboundEvent], days: int | None = None) -> list[m.InboundEvent]:
    """Replay events with times moved like the plan, so 'tomorrow' still means the planned day, and the weekday
    names in subject, text and transcript moved with them, so 'Monday, not Friday' still matches the dates."""
    days = shift_days() if days is None else days
    if not days:
        return list(events)
    delta = timedelta(days=days)
    return [
        e.model_copy(update={
            "sent_at": e.sent_at + delta,
            "received_at": e.received_at + delta,
            "subject": shift_weekdays(e.subject, days),
            "text": shift_weekdays(e.text, days),
            "transcript": shift_weekdays(e.transcript, days),
        })
        for e in events
    ]


def shift_weekdays(text: str | None, days: int) -> str | None:
    if not text or not days % 7:
        return text

    def swap(match: re.Match) -> str:
        word = match.group(0)
        name = WEEKDAYS[(WEEKDAYS.index(word.lower()) + days) % 7]
        return name.upper() if word.isupper() else name.capitalize() if word[0].isupper() else name

    return WEEKDAY_PATTERN.sub(swap, text)


def _project_json() -> m.Project:
    try:
        raw = json.loads((PROJECT_DIR / "project.json").read_text(encoding="utf-8"))
        return m.Project.model_validate(raw["project"])
    except (OSError, ValueError, KeyError) as error:
        raise DemoDataError(f"data/project/project.json is not usable: {error}") from None


def _schedule_xlsx() -> m.Plan:
    try:
        book = _xlsx().read_xlsx(PROJECT_DIR / "schedule.xlsx")
        info = {row[0]: row[1] for row in book["Info"][1:] if len(row) >= 2}
        tasks = []
        for row in book["Schedule"][1:]:
            task_id, name, unit, crew, start, end, preds, inspection, status = (row + [None] * 9)[:9]
            tasks.append({
                "id": task_id, "name": name, "unit": unit, "crew": crew, "start": start, "end": end,
                "depends_on": [p.strip() for p in str(preds).split(",") if p.strip()] if preds else [],
                "requires_inspection": inspection, "status": status or "planned",
            })
        resources = []
        for row in book["Resources"][1:]:
            line_id, item, kind, at, planned, actual, unit = (row + [None] * 8)[:7]
            resources.append({"id": line_id, "item": item, "kind": kind, "date": at, "planned": planned,
                              "actual": actual, "unit": unit or "count"})
        return m.Plan.model_validate({"tasks": tasks, "resources": resources, "handover": info["Handover"]})
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise DemoDataError(f"data/project/schedule.xlsx is not usable: {error}") from None


def _xlsx():
    """data/project/xlsx.py reads the workbook without a spreadsheet library; it lives with the generator."""
    spec = importlib.util.spec_from_file_location("aurora_project_xlsx", PROJECT_DIR / "xlsx.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
