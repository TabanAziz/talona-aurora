"""Resolve only registered or already received local PDF sources for a revision."""
import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from app.core import config, models as m
from app.core.store import store


def _safe(value) -> bool:
    return isinstance(value, str) and bool(value) and value not in (".", "..") and all(
        char.isalnum() or char in "-_." for char in value)


def _local_pdf(url: str | None) -> Path | None:
    if not url or not url.startswith(("/media/files/", "/media/mock/")):
        return None
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    if "\0" in path:
        return None
    for prefix, root in (("/media/files/", config.data_dir() / "files"), ("/media/mock/", config.ROOT / "mocks" / "assets")):
        if path.startswith(prefix):
            base = root.resolve()
            target = (base / path[len(prefix):]).resolve()
            return target if base in target.parents and target.is_file() else None
    return None


def _attachments(event: m.InboundEvent, sheet: str, revision: str) -> list[Path]:
    pdfs = [attachment for attachment in event.attachments if attachment.kind == "pdf"
            or attachment.media_type == "application/pdf" or attachment.name.lower().endswith(".pdf")]
    named = [attachment for attachment in pdfs
             if re.search(rf"(?<![A-Za-z0-9]){re.escape(sheet)}(?![A-Za-z0-9])", attachment.name, re.IGNORECASE)]
    candidates = named or (pdfs if len(pdfs) == 1 else [])
    explicit = []
    for attachment in candidates:
        stated = re.search(r"\brev(?:ision)?[\s_.-]*([A-Za-z0-9]+)", attachment.name, re.IGNORECASE)
        if stated and stated[1].casefold() != revision.casefold():
            continue
        explicit.append(attachment)
    # Multiple indistinguishable PDFs are ambiguous, not an invitation to compare the first one.
    if len(explicit) != 1:
        return []
    path = _local_pdf(explicit[0].url)
    return [path] if path is not None else []


def _arrived(event: m.InboundEvent, sheet: str) -> list[tuple[str, m.InboundEvent]]:
    events = {raw["id"]: raw for raw in store().list("events")}
    found = []
    for fact in store().list("facts"):
        data = fact.get("data") or {}
        if fact.get("type") != "drawing_revision" or data.get("sheet") != sheet or fact.get("event_id") == event.id:
            continue
        raw = events.get(fact.get("event_id"))
        if raw is None or not _safe(data.get("revision")):
            continue
        try:
            source = m.InboundEvent.model_validate(raw)
        except ValidationError:
            continue
        if source.received_at <= event.received_at:
            found.append((data["revision"], source))
    return sorted(found, key=lambda pair: pair[1].received_at, reverse=True)


def _registered(register: Path, sheet: str, revision: str) -> list[Path]:
    candidate = register / sheet / revision / "sheet.pdf"
    return [candidate] if candidate.is_file() else []


def _unavailable(event: m.InboundEvent, fact: m.Fact, sheet: str, revision: str) -> None:
    digest = hashlib.sha256("\0".join((event.id, sheet, revision)).encode()).hexdigest()[:24]
    entry_id = f"r-drawing-unavailable-{digest}"
    store().put("record", entry_id, m.RecordEntry(
        id=entry_id, at=event.received_at, kind="info", title=f"Drawing comparison unavailable: {sheet} Rev {revision}",
        detail="A readable previous and current PDF of the same page size or a complete geometry pair is not available.",
        actor="Aurora", source_event_ids=[event.id], refs={"sheet": sheet, "revision": revision, "fact": fact.id}))


def fallback(event: m.InboundEvent, fact: m.Fact, register: Path, previous: str | None) -> m.DrawingDiff | None:
    from .real import compare

    sheet, revision = fact.data.get("sheet"), fact.data.get("revision")
    if fact.event_id != event.id or not _safe(sheet) or not _safe(revision) or previous is not None and not _safe(previous):
        return None
    earlier = _arrived(event, sheet)
    if previous is None:
        folder = register / sheet
        registered = sorted(child.name for child in folder.iterdir()
                            if _safe(child.name) and child.name < revision and (child / "sheet.pdf").is_file()) if folder.is_dir() else []
        previous = registered[-1] if registered else next((rev for rev, _ in earlier if rev != revision), None)
    if previous is not None:
        before = _registered(register, sheet, previous)
        for rev, source in earlier:
            if rev == previous:
                before.extend(_attachments(source, sheet, previous))
        after = _attachments(event, sheet, revision) or _registered(register, sheet, revision)
        diff_id = "d-" + "-".join("".join(char for char in value.lower() if char.isalnum())
                                     for value in (sheet, previous, revision)) + "-pdf"
        for old in dict.fromkeys(before):
            for new in dict.fromkeys(after):
                result = compare(old, new, diff_id=diff_id, sheet=sheet, title="PDF drawing comparison",
                                 from_rev=previous, to_rev=revision)
                if result is not None:
                    return result
    _unavailable(event, fact, sheet, revision)
    return None
