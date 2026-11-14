"""A revision register from committed/imported files and actual received evidence."""
import re
from urllib.parse import unquote, urlsplit

from app.core import config
from app.core.store import store
from .storage import safe


def _identity(value) -> str | None:
    try:
        return safe(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _media(url: str | None, project_id: str) -> str | None:
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    if "\0" in path:
        return None
    scoped = f"/media/projects/{project_id}/"
    if path.startswith(scoped):
        path = "/media/" + path[len(scoped):]
    roots = [("files", config.data_dir() / "files")]
    if config.project_directory.get() is None:
        roots.append(("mock", config.ROOT / "mocks" / "assets"))
    for kind, root in roots:
        prefix = f"/media/{kind}/"
        if path.startswith(prefix):
            target = (root / path[len(prefix):]).resolve()
            if root.resolve() in target.parents and target.is_file():
                return f"/media/projects/{project_id}/{kind}/{path[len(prefix):]}"
    return None


def register(project_id: str) -> dict:
    entries = {}
    base = config.drawings_dir()
    events = {event["id"]: event for event in store().list("events")}
    facts = [fact for fact in store().list("facts") if fact.get("type") == "drawing_revision"]

    def entry(sheet, revision):
        sheet, revision = _identity(sheet), _identity(revision)
        if not sheet or not revision:
            return None
        return entries.setdefault((sheet, revision), {
            "revision": revision, "pdf_url": None, "image_url": None, "geometry_url": None,
            "received_at": None, "source_event_ids": [], "has_geometry": False,
        })

    if base.is_dir():
        for sheet in sorted(path for path in base.iterdir() if path.is_dir()):
            for revision in sorted(path for path in sheet.iterdir() if path.is_dir()):
                available = [(field, filename) for field, filename in (
                    ("pdf_url", "sheet.pdf"), ("image_url", "sheet.png"), ("geometry_url", "geometry.json"))
                    if (revision / filename).is_file()]
                if not available:
                    continue
                current = entry(sheet.name, revision.name)
                if current is not None:
                    prefix = f"/media/projects/{project_id}/drawings/{sheet.name}/{revision.name}"
                    for field, filename in available:
                        current[field] = f"{prefix}/{filename}"
                    current["has_geometry"] = bool(current["geometry_url"])

    for fact in facts:
        data = fact.get("data") or {}
        current = entry(data.get("sheet"), data.get("revision"))
        if current is None:
            continue
        source = events.get(fact.get("event_id"))
        if source is None:
            continue
        event_id = source["id"]
        if event_id not in current["source_event_ids"]:
            current["source_event_ids"].append(event_id)
        received = source.get("received_at")
        if received and (current["received_at"] is None or received > current["received_at"]):
            current["received_at"] = received
        attachments = [attachment for attachment in source.get("attachments", [])
                       if attachment.get("kind") == "pdf" or attachment.get("media_type") == "application/pdf"
                       or attachment.get("name", "").lower().endswith(".pdf")]
        # A message with multiple drawings must identify which PDF belongs to the fact.
        named = [attachment for attachment in attachments
                 if re.search(rf"(?<![A-Za-z0-9]){re.escape(data['sheet'])}(?![A-Za-z0-9])",
                              attachment.get("name", ""), re.IGNORECASE)]
        candidates = named or attachments
        candidates = [attachment for attachment in candidates
                      if (match := re.search(r"\brev(?:ision)?[\s_.-]*([A-Za-z0-9]+)", attachment.get("name", ""), re.IGNORECASE)) is None
                      or match[1].casefold() == data["revision"].casefold()]
        if len(candidates) == 1 and current["pdf_url"] is None:
            current["pdf_url"] = _media(candidates[0].get("url"), project_id)

    for diff in store().list("diffs"):
        for revision, image_key, geometry_key in ((diff.get("from_rev"), "before_url", "before_geometry_url"),
                                                   (diff.get("to_rev"), "after_url", "after_geometry_url")):
            current = entry(diff.get("sheet"), revision)
            if current is not None:
                current["image_url"] = current["image_url"] or _media(diff.get(image_key), project_id)
                current["geometry_url"] = current["geometry_url"] or _media(diff.get(geometry_key), project_id)
                current["has_geometry"] = bool(current["geometry_url"])

    from app.record.real import current_revision
    sheets = []
    for sheet in sorted({key[0] for key in entries}):
        revisions = [value for (sheet_id, _), value in entries.items() if sheet_id == sheet]
        revisions.sort(key=lambda value: (value["received_at"] is not None, value["received_at"] or "", value["revision"]))
        sourced_current = current_revision(sheet)
        current = sourced_current.data.get("revision") if sourced_current else revisions[-1]["revision"]
        sheets.append({"id": sheet, "title": sheet + " floor plan", "current_revision": current, "revisions": revisions})
    return {"sheets": sheets}
