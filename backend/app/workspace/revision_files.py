"""Register received structured drawing files against the revision named in the message."""
import json
from urllib.parse import unquote, urlsplit

from app.core import config
from .geometry import Geometry
from .storage import safe, write_json


def stage(event, facts):
    if config.project_directory.get() is None:
        return
    revisions = {(fact.data.get("sheet"), fact.data.get("revision")) for fact in facts
                 if fact.event_id == event.id and fact.type == "drawing_revision"}
    if not revisions:
        return
    root = (config.data_dir() / "files").resolve()
    for attachment in event.attachments:
        if not attachment.name.lower().endswith(".json") or not attachment.url:
            continue
        parsed = urlsplit(attachment.url)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith("/media/files/"):
            continue
        source = (root / unquote(parsed.path.removeprefix("/media/files/"))).resolve()
        if root not in source.parents or not source.is_file() or source.stat().st_size > 5 * 1024 * 1024:
            continue
        try:
            raw = json.loads(source.read_text(encoding="utf-8-sig"))
            geometry = Geometry.model_validate(raw.get("geometry", raw))
            if (geometry.sheet, geometry.revision) not in revisions:
                continue
            target = config.drawings_dir() / safe(geometry.sheet) / safe(geometry.revision)
            value = geometry.model_dump(mode="json")
            existing = target / "geometry.json"
            if existing.exists():
                continue
            from .api import _render_geometry
            write_json(existing, value)
            _render_geometry(value, target)
        except (ValueError, OSError, AttributeError):
            continue
