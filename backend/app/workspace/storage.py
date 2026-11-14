"""Workspace files live beneath DATA_DIR, separate from committed example data."""
import json
import hashlib
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.core import config
from app.core import models as m
from app.core.store import Store, store

LOCK = threading.RLock()
_catalogs: dict[Path, Store] = {}
SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")


def safe(value: str) -> str:
    if not SAFE.fullmatch(value):
        raise ValueError("Use letters, numbers, periods, hyphens or underscores in sheet and revision ids")
    return value


def root() -> Path:
    path = config.base_data_dir() / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def catalog() -> Store:
    path = (root() / "catalog.sqlite").resolve()
    with LOCK:
        if path not in _catalogs:
            _catalogs[path] = Store(path)
        return _catalogs[path]


def directory(project_id: str) -> Path:
    return root() / "projects" / safe(project_id)


@contextmanager
def selected(project_id: str, path: Path):
    token = config.project_directory.set(path)
    identity = config.project_id.set(project_id)
    try:
        yield
    finally:
        config.project_id.reset(identity)
        config.project_directory.reset(token)


def default_project() -> dict:
    from app import demodata
    # Read the real default store without inheriting the request's selection.
    token = config.project_directory.set(None)
    try:
        return store().get("project", "current") or demodata.load().project.model_dump(mode="json")
    finally:
        config.project_directory.reset(token)


def metadata(project: dict, created_at: str, *, default=False) -> dict:
    return {"id": project["id"], "name": project["name"], "unit_count": len(project["units"]),
            "crew_count": len(project["crews"]), "sheet_count": sheet_count(project["id"], default=default),
            "created_at": created_at, "is_default": default}


def sheet_count(project_id: str, *, default=False) -> int:
    from .drawings import register
    path = None if default else directory(project_id)
    token = config.project_directory.set(path)
    try:
        return len(register(project_id)["sheets"])
    finally:
        config.project_directory.reset(token)


def projects() -> list[dict]:
    from .branding import read as read_brand
    base = default_project()
    rows = [{**row, "sheet_count": sheet_count(row["id"])} for row in catalog().list("projects")]
    return [{**row, "brand": read_brand(row["id"])} for row in [metadata(base, "", default=True), *rows] if not is_deleted(row["id"])]


def is_deleted(project_id: str) -> bool:
    return catalog().get("deleted_projects", project_id) is not None


def deleted_projects() -> list[dict]:
    return list(reversed(catalog().list("deleted_projects")))


def delete_project(project_id: str) -> dict:
    safe(project_id)
    with LOCK:
        previous = catalog().get("deleted_projects", project_id)
        if previous:
            return previous
        base = default_project()
        project = metadata(base, "", default=True) if project_id == base["id"] else catalog().get("projects", project_id)
        if not project:
            raise ValueError("Project not found")
        deleted = {**project, "deleted_at": now()}
        catalog().put("deleted_projects", project_id, deleted)
        return deleted


def restore_project(project_id: str) -> dict:
    safe(project_id)
    with LOCK:
        deleted = catalog().get("deleted_projects", project_id)
        if not deleted:
            raise ValueError("Deleted project not found")
        catalog().delete("deleted_projects", project_id)
        return {key:value for key,value in deleted.items() if key != "deleted_at"}


def seed_current() -> dict:
    seed = json.loads((config.data_dir() / "seed.json").read_text(encoding="utf-8"))
    target = store()
    target.clear()
    target.put("project", "current", seed["project"])
    target.put("plan", "current", seed["plan"])
    for machine in seed.get("machines", []):
        target.put("machines", machine["id"], machine)
    seed_knowledge(seed)
    return seed["project"]


def seed_knowledge(seed: dict | None = None) -> None:
    """Restore reviewed setup evidence without clearing subsequent messages or changing the live plan."""
    from app.core import pipeline
    with pipeline._lock:
        _seed_knowledge(seed)


def _seed_knowledge(seed: dict | None = None) -> None:
    if seed is None:
        seed = json.loads((config.data_dir() / "seed.json").read_text(encoding="utf-8"))
    target = store()
    now = seed["created_at"]
    provenance = seed.get("import") or {}
    source_names = [item["name"] for item in provenance.get("sources") or []]
    model_used = provenance.get("model_used")
    origin = ("The setup was proposed by a model and reviewed when the project was created. "
              "Its geometry is conceptual, not a measured construction drawing."
              if model_used else "The reviewed setup was imported as structured project data."
              if model_used is False else "This is the reviewed project setup; original proposal method was not retained.")
    if source_names:
        origin += " Imported sources: " + ", ".join(source_names) + "."
    assumptions = seed.get("assumptions") or []
    warnings = provenance.get("warnings") or []
    project = seed["project"]
    description = project.get("description", "").strip()
    if len(description) > 320:
        description = description[:317].rstrip() + "..."
    setup_text = (f"Reviewed project setup for {project['name']}. {origin}\n"
                  f"Description: {description or 'Not provided.'}\n"
                  f"Units: {', '.join(project['units']) or 'Not provided.'}\n"
                  f"Crews: {', '.join(project['crews']) or 'Not provided.'}\n"
                  f"{len(assumptions)} setup assumptions and {len(warnings)} review notes are preserved "
                  "in the attached complete reviewed setup, together with the original input and source details.")
    setup_id = "workspace-project-setup"
    attachments = []
    for source in provenance.get("sources") or []:
        source_file = source.get("file")
        if source_file and (config.data_dir() / "files" / "import" / safe(source_file)).is_file():
            attachments.append({"kind": "pdf" if source.get("kind") == "pdf" else "file", "name": source["name"],
                                "url": f"/media/files/import/{source_file}"})
    write_json(config.data_dir() / "files" / "import" / "reviewed-project-setup.json", seed)
    attachments.append({"kind": "file", "name": "Complete reviewed project setup.json",
                        "url": "/media/files/import/reviewed-project-setup.json", "media_type": "application/json"})
    target.put("events", setup_id, m.InboundEvent(
        id=setup_id, channel="schedule", sent_at=now, received_at=now,
        sender="Project setup", sender_role="Reviewed project import", text=setup_text, attachments=attachments))
    reserved = {task["id"] for task in seed["plan"]["tasks"]}
    def record_id(value):
        while value in reserved:
            value += "_"
        reserved.add(value)
        return value
    setup_record_id = record_id("r-workspace-project-setup")
    target.put("record", setup_record_id, m.RecordEntry(
        id=setup_record_id, at=now, kind="info", title="Reviewed project setup imported",
        detail=f"{origin} Assumptions: {'; '.join(assumptions) or 'None recorded'}. "
               f"Review notes: {'; '.join(warnings) or 'None recorded'}.", actor="Project setup",
        source_event_ids=[setup_id], refs={"project": seed["project"]["id"]}))
    for drawing in seed.get("drawings", []):
        event_id = f"workspace-{drawing['sheet']}-{drawing['revision']}"
        rooms = [room["label"] for room in (drawing.get("geometry") or {}).get("rooms", [])]
        text = (f"Imported {drawing['sheet']} revision {drawing['revision']} during reviewed project setup. "
                f"Registered for units {', '.join(seed['project']['units'])}. "
                f"Room labels: {', '.join(rooms) if rooms else 'not provided'}. {origin}")
        event = {"id": event_id, "channel": "schedule", "sent_at": now, "received_at": now,
                 "sender": "Project setup", "text": text, "attachments": []}
        target.put("events", event_id, event)
        target.put("facts", event_id, {"id": event_id, "event_id": event_id, "type": "drawing_revision",
                   "subject": text, "confidence": 1, "quote": text,
                   "data": {"sheet": drawing["sheet"], "revision": drawing["revision"],
                            "units": seed["project"]["units"]}})
        drawing_record_id = record_id(f"r-{event_id}")
        target.put("record", drawing_record_id, m.RecordEntry(
            id=drawing_record_id, at=now, kind="change",
            title=f"{drawing['sheet']} Rev {drawing['revision']} registered at project setup",
            detail=text, actor="Project setup", source_event_ids=[event_id],
            refs={"sheet": drawing["sheet"], "revision": drawing["revision"]}))
    for task in seed["plan"]["tasks"]:
        digest = hashlib.sha256(task["id"].encode()).hexdigest()[:20]
        task_event_id = f"workspace-task-{digest}"
        text = (f"Reviewed imported programme: {task['name']} (task {task['id']}), "
                f"unit {task.get('unit') or 'not specified'}, crew {task['crew']}, "
                f"start {task['start']}, end {task['end']}, status {task.get('status', 'planned')}. "
                f"Dependencies: {', '.join(task.get('depends_on') or []) or 'none'}. "
                f"Required inspection: {task.get('requires_inspection') or 'not specified'}. "
                f"{origin} This programme is planned work, not permission to start or proof of completion.")
        target.put("events", task_event_id, m.InboundEvent(
            id=task_event_id, channel="schedule", sent_at=now, received_at=now,
            sender="Project setup", sender_role="Reviewed project import", text=text))
        # QA displays task ids in the plan and accepts only record ids backed by real events.
        target.put("record", task["id"], m.RecordEntry(
            id=task["id"], at=now, kind="info", title=f"Imported programme: {task['name']}",
            detail=text, actor="Project setup", source_event_ids=[task_event_id],
            refs={"task": task["id"], "unit": task.get("unit") or "", "crew": task["crew"]}))


def identifier(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:16]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temp.replace(path)
