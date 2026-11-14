"""Drawing comparison from the geometry of two revisions of a sheet.

Each revision in the drawing register (data/drawings/<sheet>/<revision>) has geometry.json and the rendered
sheet.png in the same frame, so walls that differ between the two geometry files give exact regions on the
images. The comparison writes before, after, overlay and crop images under DATA_DIR/files/diffs/<diff id>/.
"""
import json
import math
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

from app.core import config
from app.core import models as m
from app.core.registry import area

DISCIPLINES = {"A": "Architectural", "E": "Electrical", "S": "Structural", "M": "Mechanical", "P": "Plumbing"}
# A region keeps the door leaf that travels with a wall inside it, plus a small margin so the mark is visible.
MARGIN_MM = 200
CROP_PADDING_MM = 1200


def register() -> Path:
    return config.drawings_dir()


def files_dir() -> Path:
    return config.data_dir() / "files" / "diffs"


def diffs_for(event: m.InboundEvent, facts: list[m.Fact]) -> list[m.DrawingDiff]:
    from app.workspace.revision_files import stage
    stage(event, facts)
    diffs: list[m.DrawingDiff] = []
    for fact in facts:
        if fact.type != "drawing_revision" or fact.event_id != event.id:
            continue
        sheet, revision = fact.data.get("sheet"), fact.data.get("revision")
        if not _safe(sheet) or not _safe(revision):
            continue
        previous = fact.data.get("replaces") or _previous_revision(sheet, revision)
        if previous and _has_revision(sheet, previous) and _has_revision(sheet, revision):
            diffs.append(compare(sheet, previous, revision))
        elif previous or not _has_revision(sheet, revision):
            fallback = area("pdfdiff").fallback(event, fact, register(), previous)
            if fallback is not None:
                diffs.append(fallback)
    return diffs


def compare(sheet: str, from_rev: str, to_rev: str) -> m.DrawingDiff:
    before_dir, after_dir = register() / sheet / from_rev, register() / sheet / to_rev
    before = json.loads((before_dir / "geometry.json").read_text(encoding="utf-8"))
    after = json.loads((after_dir / "geometry.json").read_text(encoding="utf-8"))
    changes = changed_walls(before, after)
    diff_id = f"d-{_slug(sheet)}-{_slug(from_rev)}-{_slug(to_rev)}"
    out = files_dir() / diff_id
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(before_dir / "sheet.png", out / "before.png")
    shutil.copyfile(after_dir / "sheet.png", out / "after.png")
    shutil.copyfile(before_dir / "geometry.json", out / "before.geometry.json")
    shutil.copyfile(after_dir / "geometry.json", out / "after.geometry.json")
    title = f"{sheet} Rev {from_rev} to Rev {to_rev}"
    (out / "overlay.svg").write_text(_svg(before, after, changes, None, title), encoding="utf-8")
    (out / "crop.svg").write_text(_svg(before, after, changes, _crop_box(after, changes), title), encoding="utf-8")
    regions = [_region(c, after["width"], after["height"]) for c in changes]
    url = f"/media/files/diffs/{diff_id}"
    return m.DrawingDiff(
        id=diff_id,
        sheet=sheet,
        title=f"{DISCIPLINES.get(sheet[:1].upper(), 'Drawing')} plan",
        from_rev=from_rev,
        to_rev=to_rev,
        before_url=f"{url}/before.png",
        after_url=f"{url}/after.png",
        overlay_url=f"{url}/overlay.svg",
        before_geometry_url=f"{url}/before.geometry.json",
        after_geometry_url=f"{url}/after.geometry.json",
        regions=regions,
        summary=_summary(changes),
    )


def changed_walls(before: dict, after: dict) -> list[dict]:
    """One change per wall id whose position, thickness or openings differ between the revisions."""
    old_walls = {w["id"]: w for w in before["walls"]}
    new_walls = {w["id"]: w for w in after["walls"]}
    changes = []
    for wall_id in list(old_walls) + [w for w in new_walls if w not in old_walls]:
        old, new = old_walls.get(wall_id), new_walls.get(wall_id)
        old_openings, new_openings = _openings(before, wall_id), _openings(after, wall_id)
        if old and new and _shape(old) == _shape(new) and old_openings == new_openings:
            continue
        kind = "moved" if old and new else ("removed" if old else "added")
        walls = [w for w in (old, new) if w]
        margin = max([MARGIN_MM] + [o["width"] + MARGIN_MM for o in old_openings + new_openings])
        xs = [v for w in walls for v in (w["x1"], w["x2"])]
        ys = [v for w in walls for v in (w["y1"], w["y2"])]
        left, top = min(xs) - margin, min(ys) - margin
        box = (left, top, max(xs) + margin - left, max(ys) + margin - top)
        room = _room_near(after, new or old)
        changes.append({"wall": wall_id, "kind": kind, "box": box, "room": room, "label": _label(kind, old, new, room)})
    return changes


def _shape(wall: dict) -> tuple:
    return wall["x1"], wall["y1"], wall["x2"], wall["y2"], wall["thickness"]


def _openings(geometry: dict, wall_id: str) -> list[dict]:
    return sorted((o for o in geometry["openings"] if o["wall"] == wall_id), key=lambda o: (o["offset"], o["kind"]))


def _label(kind: str, old: dict | None, new: dict | None, room: str) -> str:
    name = f"{(new or old)['kind'].capitalize()} {room}".strip()
    if kind != "moved":
        return f"{name}, {kind}"
    dx, dy = new["x1"] - old["x1"], new["y1"] - old["y1"]
    if (dx, dy) == (0, 0) or (new["x2"] - old["x2"], new["y2"] - old["y2"]) != (dx, dy):
        return f"{name}, changed"
    parts = []
    if dy:
        parts.append(f"{abs(dy)} mm {'south' if dy > 0 else 'north'}")
    if dx:
        parts.append(f"{abs(dx)} mm {'east' if dx > 0 else 'west'}")
    return f"{name}, {' and '.join(parts)}"


def _room_near(geometry: dict, wall: dict) -> str:
    """The room label closest to the wall's midpoint; rooms are label points, not outlines."""
    mx, my = (wall["x1"] + wall["x2"]) / 2, (wall["y1"] + wall["y2"]) / 2
    rooms = sorted((room for room in geometry.get("rooms", []) if wall.get("level") is None or room.get("level") == wall.get("level")), key=lambda r: math.hypot(r["x"] - mx, r["y"] - my))
    return rooms[0]["label"] if rooms else ""


def _summary(changes: list[dict]) -> str:
    if not changes:
        return "No wall changed between the two revisions."
    rooms = sorted({c["room"] for c in changes if c["room"]})
    count = "One wall" if len(changes) == 1 else f"{len(changes)} walls"
    verb = "moved" if all(c["kind"] == "moved" for c in changes) else "changed"
    return f"{count} {verb} ({', '.join(rooms)})."


def _crop_box(geometry: dict, changes: list[dict]) -> tuple | None:
    if not changes:
        return None
    left = min(c["box"][0] for c in changes) - CROP_PADDING_MM
    top = min(c["box"][1] for c in changes) - CROP_PADDING_MM
    right = max(c["box"][0] + c["box"][2] for c in changes) + CROP_PADDING_MM
    bottom = max(c["box"][1] + c["box"][3] for c in changes) + CROP_PADDING_MM
    left, top = max(0, left), max(0, top)
    return left, top, min(geometry["width"], right) - left, min(geometry["height"], bottom) - top


def _svg(before: dict, after: dict, changes: list[dict], box: tuple | None, title: str) -> str:
    """Both revisions in one picture: unchanged walls dark, the old position red and dashed, the new one green."""
    width, height = after["width"], after["height"]
    view = box or (0, 0, width, height)
    changed = {c["wall"] for c in changes}
    old_walls = {w["id"]: w for w in before["walls"]}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(str(round(v)) for v in view)}" '
        f'role="img" aria-label="{escape(title)}, red removed, green added, DEMO DATA">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
    ]
    for wall in after["walls"]:
        color = "#1b7a3d" if wall["id"] in changed else "#252525"
        parts.extend(_wall_svg(after, wall, color, dashed=False))
    for wall_id in sorted(changed):
        if wall_id in old_walls:
            parts.extend(_wall_svg(before, old_walls[wall_id], "#c62828", dashed=True))
    for room in after.get("rooms", []):
        size = 300 if len(room["label"]) < 4 else 200
        parts.append(
            f'<text x="{room["x"]}" y="{room["y"]}" font-family="Arial, sans-serif" font-size="{size}" '
            f'fill="#5f5f5a" text-anchor="middle" dominant-baseline="middle">{escape(room["label"])}</text>'
        )
    for change in changes:
        x, y, w, h = change["box"]
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="150" fill="none" stroke="#1d5bd8" stroke-width="40"/>'
        )
    parts.append(
        f'<text x="{view[0] + 300}" y="{view[1] + view[3] - 300}" font-family="Arial, sans-serif" font-size="260" '
        f'fill="#5f5f5a">{escape(title)}  /  DEMO DATA</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _wall_svg(geometry: dict, wall: dict, color: str, dashed: bool) -> list[str]:
    dx, dy = wall["x2"] - wall["x1"], wall["y2"] - wall["y1"]
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    openings = _openings(geometry, wall["id"])
    cuts = [(o["offset"], o["offset"] + o["width"]) for o in openings]
    dash = ' stroke-dasharray="300 200"' if dashed else ""
    stroke = f'stroke="{color}" stroke-width="{wall["thickness"]}"{dash}'
    out, start = [], 0.0
    for cut_start, cut_end in cuts + [(length, length)]:
        if cut_start > start:
            out.append(_line(wall, ux, uy, start, cut_start, stroke))
        start = max(start, cut_end)
    for opening in openings:
        sx, sy = wall["x1"] + ux * opening["offset"], wall["y1"] + uy * opening["offset"]
        ex, ey = sx + ux * opening["width"], sy + uy * opening["width"]
        if opening["kind"] == "window":
            out.append(f'<line x1="{sx:.0f}" y1="{sy:.0f}" x2="{ex:.0f}" y2="{ey:.0f}" stroke="#777777" stroke-width="30"/>')
            continue
        r = opening["width"]
        tx, ty = sx - uy * r, sy + ux * r
        out.append(f'<line x1="{sx:.0f}" y1="{sy:.0f}" x2="{tx:.0f}" y2="{ty:.0f}" stroke="{color}" stroke-width="20"/>')
        out.append(f'<path d="M {tx:.0f} {ty:.0f} A {r} {r} 0 0 0 {ex:.0f} {ey:.0f}" fill="none" stroke="#777777" stroke-width="10"/>')
    return out


def _line(wall: dict, ux: float, uy: float, a: float, b: float, stroke: str) -> str:
    x1, y1 = wall["x1"] + ux * a, wall["y1"] + uy * a
    x2, y2 = wall["x1"] + ux * b, wall["y1"] + uy * b
    return f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" {stroke}/>'


def _previous_revision(sheet: str, revision: str) -> str | None:
    folder = register() / sheet
    if not folder.is_dir():
        return None
    earlier = sorted(p.name for p in folder.iterdir() if _has_revision(sheet, p.name) and p.name < revision)
    return earlier[-1] if earlier else None


def _has_revision(sheet: str, revision: str) -> bool:
    if not _safe(sheet) or not _safe(revision):
        return False
    return (register() / sheet / revision / "geometry.json").is_file() and (register() / sheet / revision / "sheet.png").is_file()


def _safe(name: object) -> bool:
    """Sheet and revision come from extracted text and become path parts, so only plain names are allowed."""
    return isinstance(name, str) and bool(name) and all(ch.isalnum() or ch in "-_." for ch in name) and name not in (".", "..")


def _slug(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _region(change: dict, width: float, height: float) -> m.DiffRegion:
    """The change's box as fractions of the sheet, cut to the sheet edges."""
    x, y, w, h = change["box"]
    left, top = max(0.0, x / width), max(0.0, y / height)
    right, bottom = min(1.0, (x + w) / width), min(1.0, (y + h) / height)
    return m.DiffRegion(x=left, y=top, w=max(0.0, right - left), h=max(0.0, bottom - top),
                        kind=change["kind"], label=change["label"])
