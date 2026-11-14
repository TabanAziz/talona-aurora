"""Cross-sheet check: a revision that moved a wall leaves the other sheets of the project out of date.

The drawing register (data/drawings/<sheet>/<revision>) is the record of revisions, so the newest revision of a
sheet is the newest one on record. When a diff moves a wall, every other sheet is compared against the new
position: a sheet that still shows the old position gets one finding, and Aurora acts on it once (a notice to the
crews who work from that sheet, a reissue request to the architect and a waiting item that a later revision of
that sheet closes). Nothing here calls the model and nothing changes a plan.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app.core import config, models as m
from app.core.registry import area
from app.core.store import store
from app.live import directory
from app.live.delivery import deliver

# A wall is in the same place when both ends agree within this; the geometry is in millimetres.
TOLERANCE_MM = 1
SUPERINTENDENT = "Superintendent"
# A sheet is named by its discipline, and the crew that works from it carries that trade in its name.
DISCIPLINE_TRADE = {"A": "Architectural", "E": "Electrical", "S": "Structural", "M": "Mechanical", "P": "Plumbing"}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
UNIT_LABEL = re.compile(r"\d+[A-Z]")


@dataclass(frozen=True)
class Finding:
    """One other sheet of the project that still shows the position a change replaced."""

    sheet: str
    revision: str
    wall: str
    unit: str
    offset_mm: int
    direction: str


def register() -> Path:
    return config.drawings_dir()


def check(diff: m.DrawingDiff) -> list[Finding]:
    """One finding per other sheet that still shows the replaced wall position, in register order."""
    findings, _skipped = evaluate(diff)
    return findings


def evaluate(diff: m.DrawingDiff) -> tuple[list[Finding], list[tuple[str, str]]]:
    """The findings, and the (sheet, revision) pairs whose newest revision has no geometry to compare."""
    source = _geometry(diff.sheet, diff.to_rev)
    if source is None:
        return [], []
    walls = [wall for wall in source.get("changed") or [] if isinstance(wall, str)]
    findings: list[Finding] = []
    skipped: list[tuple[str, str]] = []
    for sheet, revision, other in _others(diff.sheet):
        if other is None:
            skipped.append((sheet, revision))
            continue
        for wall in walls:
            shift = _shift(_wall(source, wall), _wall(other, wall))
            if shift is None:
                continue
            findings.append(Finding(sheet=sheet, revision=revision, wall=wall, unit=_unit(wall, other),
                                    offset_mm=shift[0], direction=shift[1]))
            break
    return findings, skipped


def on_diff(diff: m.DrawingDiff, event: m.InboundEvent) -> None:
    """Act on a new diff once per finding, record what could not be checked, and close reissued sheets."""
    findings, skipped = evaluate(diff)
    # A change a guest reported is answered in the guest's own thread: the same scope the outbox uses keeps the
    # crews and the architect out of a conversation that started in a private chat.
    with area("guest").delivery_scope([event.id]):
        for sheet, revision in skipped:
            _record_skip(diff, sheet, revision, event)
        for finding in findings:
            _act(finding, diff, event)
        _close_reissued(diff, event)


def _act(finding: Finding, diff: m.DrawingDiff, event: m.InboundEvent) -> None:
    entry_id = f"r-cross-{diff.id}-{_slug(finding.sheet)}"
    if store().get("record", entry_id) is not None:
        return

    crews = _crews(finding.sheet)
    if crews:
        for crew in crews:
            _send(m.OutboundMessage(
                id=f"o-cross-outdated-{diff.id}-{_slug(finding.sheet)}-{_slug(crew)}", channel="telegram",
                to=crew, created_at=event.received_at, buttons=["Confirmed"], media_url=_crop(diff),
                text=(f"{finding.sheet} Rev {finding.revision} no longer matches {diff.sheet} Rev {diff.to_rev}. "
                      f"The wall {finding.wall} in {finding.unit} sits {finding.offset_mm} mm {finding.direction} "
                      f"of the new position. Do not build from {finding.sheet} until it is reissued. "
                      f"Reply Confirmed when you have the new sheet."),
                reason="Outdated sheet for the work on site",
            ), event)
    else:
        _send(m.OutboundMessage(
            id=f"o-cross-outdated-{diff.id}-{_slug(finding.sheet)}-superintendent", channel="telegram",
            to=_superintendent(), created_at=event.received_at, buttons=["Confirmed"], media_url=_crop(diff),
            text=(f"{finding.sheet} Rev {finding.revision} no longer matches {diff.sheet} Rev {diff.to_rev}, "
                  f"and no crew is known for it. The wall {finding.wall} in {finding.unit} sits "
                  f"{finding.offset_mm} mm {finding.direction} of the new position. Do not build from "
                  f"{finding.sheet} until it is reissued. Nobody was guessed as the crew."),
            reason="Outdated sheet without a known crew",
        ), event)

    _send(m.OutboundMessage(
        id=f"o-cross-reissue-{diff.id}-{_slug(finding.sheet)}", channel="telegram", to=_architect(),
        created_at=event.received_at, buttons=["Will reissue"], reason="Reissue the outdated sheet",
        text=(f"The newest {diff.sheet} moved wall {finding.wall} in {finding.unit} {finding.offset_mm} mm "
              f"{OPPOSITE.get(finding.direction, finding.direction)}. {finding.sheet} Rev {finding.revision} still "
              f"shows the old position, so the crews would build in the wrong place. Please reissue {finding.sheet}."),
    ), event)

    waiting_id = f"w-cross-{diff.id}-{_slug(finding.sheet)}"
    if store().get("waiting", waiting_id) is None:
        store().put("waiting", waiting_id, m.WaitingItem(
            id=waiting_id, on=_architect(), what=f"Reissue {finding.sheet} after the change on {diff.sheet}",
            since=event.received_at, due=_work_start(finding.sheet, event.received_at),
            source_event_ids=[event.id],
        ))

    store().put("record", entry_id, m.RecordEntry(
        id=entry_id, at=event.received_at, kind="change",
        title=f"{finding.sheet} Rev {finding.revision} is out of date",
        detail=(f"{finding.sheet} Rev {finding.revision} no longer matches {diff.sheet} Rev {diff.to_rev}. "
                f"The wall {finding.wall} in {finding.unit} sits {finding.offset_mm} mm {finding.direction} of the "
                f"new position. The crews who work from {finding.sheet} and the architect were told."),
        actor="Aurora", source_event_ids=[event.id],
        refs={"outdated_sheet": finding.sheet, "source_change": diff.id, "wall": finding.wall,
              "revision": finding.revision},
    ))


def _record_skip(diff: m.DrawingDiff, sheet: str, revision: str, event: m.InboundEvent) -> None:
    entry_id = f"r-cross-skip-{diff.id}-{_slug(sheet)}"
    if store().get("record", entry_id) is not None:
        return
    store().put("record", entry_id, m.RecordEntry(
        id=entry_id, at=event.received_at, kind="info", title=f"{sheet} was not cross-checked",
        detail=(f"The newest revision of {sheet} ({revision}) has no geometry, so it was not compared with "
                f"{diff.sheet} Rev {diff.to_rev}."),
        actor="Aurora", source_event_ids=[event.id], refs={"skipped_sheet": sheet, "source_change": diff.id},
    ))


def _close_reissued(diff: m.DrawingDiff, event: m.InboundEvent) -> None:
    """A new revision of an outdated sheet closes the reissue request once its walls match again."""
    for raw in store().list("record"):
        refs = raw.get("refs") or {}
        if refs.get("outdated_sheet") != diff.sheet or not refs.get("source_change"):
            continue
        source = store().get("diffs", refs["source_change"])
        if source is None:
            continue
        waiting_id = f"w-cross-{source['id']}-{_slug(diff.sheet)}"
        item = store().get("waiting", waiting_id)
        if item is None or item.get("status") != "open":
            continue
        wall = refs.get("wall", "")
        wanted = _wall(_geometry(source["sheet"], source["to_rev"]), wall)
        now = _wall(_geometry(diff.sheet, diff.to_rev), wall)
        if wanted is None or now is None or _shift(wanted, now) is not None:
            continue
        store().put("waiting", waiting_id, {**item, "status": "done"})
        closed_id = f"r-cross-closed-{source['id']}-{_slug(diff.sheet)}"
        if store().get("record", closed_id) is not None:
            continue
        store().put("record", closed_id, m.RecordEntry(
            id=closed_id, at=event.received_at, kind="change",
            title=f"{diff.sheet} Rev {diff.to_rev} matches again",
            detail=(f"Wall {wall} in {diff.sheet} Rev {diff.to_rev} is back in the position of "
                    f"{source['sheet']} Rev {source['to_rev']}, so the reissue request is done."),
            actor="Aurora", source_event_ids=[event.id],
            refs={"closed_sheet": diff.sheet, "source_change": source["id"], "wall": wall,
                  "revision": diff.to_rev},
        ))


def _guest_caused(event: m.InboundEvent) -> bool:
    """A message a guest sent, or one the guest channel routed: its answer stays in that private thread."""
    return event.id.startswith("guest-") or store().get("guest_routes", event.id) is not None


def _send(message: m.OutboundMessage, event: m.InboundEvent) -> None:
    """Deliver once and keep the record of what was sent, like the outbox does for its own messages."""
    stored = deliver(message)
    entry_id = f"r-out-{stored.id}"
    if store().get("record", entry_id) is not None:
        return
    label = {"sent": "Sent to", "simulated": "Simulated message to", "queued": "Queued for",
             "failed": "Delivery failed to"}[stored.status]
    # The message keeps the label of the role it answers, but a guest-caused notice is delivered to the guest.
    recipient = "the guest who reported it" if _guest_caused(event) else stored.to
    store().put("record", entry_id, m.RecordEntry(
        id=entry_id, at=stored.created_at, kind="notice", title=f"{label} {recipient}", detail=stored.text,
        actor="Aurora", source_event_ids=[event.id], refs={"message": stored.id},
    ))


def _crews(sheet: str) -> list[str]:
    """Who works from the outdated sheet: the record first, then the trade of the sheet, then the plan."""
    crews = {contact.name for contact in directory.crews()}
    from_record = [item["on"] for item in store().list("waiting")
                   if item.get("status") == "open" and item.get("on") in crews
                   and sheet.lower() in (item.get("what") or "").lower()]
    if from_record:
        return list(dict.fromkeys(from_record))
    trade = DISCIPLINE_TRADE.get(sheet[:1].upper(), "")
    from_trade = [name for name in sorted(crews) if trade and name.lower().startswith(trade.lower())]
    if from_trade:
        return from_trade
    return _task_crews(_units(sheet))


def _task_crews(units: set[str]) -> list[str]:
    plan = store().get("plan", "current") or {}
    names: list[str] = []
    for task in plan.get("tasks", []):
        crew = task.get("crew")
        if task.get("unit") in units and crew and crew not in names:
            names.append(crew)
    return names


def _work_start(sheet: str, now: datetime) -> datetime | None:
    """The earliest start the crews on that sheet still have ahead of them."""
    plan = store().get("plan", "current") or {}
    starts = []
    for task in plan.get("tasks", []):
        if task.get("unit") not in _units(sheet):
            continue
        start = _when(task.get("start"))
        if start is not None and start >= now:
            starts.append(start)
    return min(starts) if starts else None


def _architect() -> str:
    return next((person.name for person in directory.people() if (person.role or "").lower() == "architect"),
                _superintendent())


def _superintendent() -> str:
    return next((person.name for person in directory.people() if (person.role or "").lower() == "superintendent"),
                SUPERINTENDENT)


def _crop(diff: m.DrawingDiff) -> str:
    if diff.overlay_url.startswith("/media/files/"):
        for name in ("crop.png", "crop.svg"):
            url = str(PurePosixPath(diff.overlay_url).with_name(name))
            base = (config.data_dir() / "files").resolve()
            target = (base / url.removeprefix("/media/files/")).resolve()
            if base in target.parents and target.is_file():
                return url
    return diff.overlay_url


def _others(sheet: str) -> list[tuple[str, str, dict | None]]:
    """Every other sheet of the register, with its newest revision and that revision's geometry."""
    if not register().is_dir():
        return []
    out = []
    for folder in sorted(register().iterdir()):
        if not folder.is_dir() or folder.name == sheet:
            continue
        revisions = sorted(child.name for child in folder.iterdir() if child.is_dir())
        if not revisions:
            continue
        newest = revisions[-1]
        out.append((folder.name, newest, _geometry(folder.name, newest)))
    return out


def _geometry(sheet: str, revision: str) -> dict | None:
    path = register() / sheet / revision / "geometry.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    # An empty wall list is no geometry to compare with, exactly like a missing file.
    return data if data.get("walls") else None


def _wall(geometry: dict | None, wall_id: str) -> dict | None:
    if geometry is None:
        return None
    return next((wall for wall in geometry["walls"] if wall.get("id") == wall_id), None)


def _shift(new: dict | None, old: dict | None) -> tuple[int, str] | None:
    """How far the old position sits from the new one, as millimetres and the direction it is off in."""
    if new is None or old is None:
        return None
    dx, dy = old["x1"] - new["x1"], old["y1"] - new["y1"]
    if abs(dx) <= TOLERANCE_MM and abs(dy) <= TOLERANCE_MM:
        return None
    if abs(dy) >= abs(dx):
        return round(abs(dy)), "south" if dy > 0 else "north"
    return round(abs(dx)), "east" if dx > 0 else "west"


def _unit(wall_id: str, geometry: dict) -> str:
    match = re.search(r"-(\d+[a-z])$", wall_id, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    wall = _wall(geometry, wall_id)
    if wall is None:
        return ""
    mx, my = (wall["x1"] + wall["x2"]) / 2, (wall["y1"] + wall["y2"]) / 2
    rooms = sorted(geometry.get("rooms") or [], key=lambda room: (room["x"] - mx) ** 2 + (room["y"] - my) ** 2)
    return rooms[0]["label"] if rooms else ""


def _units(sheet: str) -> set[str]:
    folder = register() / sheet
    if not folder.is_dir():
        return set()
    revisions = sorted(child.name for child in folder.iterdir() if child.is_dir())
    if not revisions:
        return set()
    geometry = _geometry(sheet, revisions[-1]) or {}
    return {room["label"] for room in geometry.get("rooms") or []
            if isinstance(room.get("label"), str) and UNIT_LABEL.fullmatch(room["label"])}


def _when(value: object) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _slug(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:10]
