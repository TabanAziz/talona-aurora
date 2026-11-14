"""Coarse changed areas from the first PDF pages, without geometry or measured positions."""
import math
import threading
from collections import deque

from PIL import Image, ImageChops, ImageDraw
import pypdfium2 as pdfium

from app.core import config, models as m
from .sources import fallback

DPI = 144
MERGE_DISTANCE_POINTS = 7
MIN_COMPONENT_AREA_POINTS2 = 50
CONTEXT_MARGIN_POINTS = 36
DIFFERENCE_LEVEL = 16
MAX_RENDER_PIXELS = 16_000_000
SUMMARY = "Compared from the PDF, positions not measured"
_render_lock = threading.Lock()


def _page_image(document, scale: float) -> Image.Image:
    page = document[0]
    bitmap = None
    try:
        bitmap = page.render(scale=scale)
        return bitmap.to_pil().convert("RGB").copy()
    finally:
        if bitmap is not None:
            bitmap.close()
        page.close()


def _pages(before_pdf, after_pdf) -> tuple[Image.Image, Image.Image] | None:
    # PDFium is not thread-safe. Only its native calls hold this lock, not the pixel comparison.
    with _render_lock:
        try:
            with pdfium.PdfDocument(before_pdf) as before, pdfium.PdfDocument(after_pdf) as after:
                if not len(before) or not len(after):
                    return None
                old_size, new_size = before.get_page_size(0), after.get_page_size(0)
                if not all(math.isclose(a, b, abs_tol=1e-6, rel_tol=0) for a, b in zip(old_size, new_size)):
                    return None
                scale = DPI / 72
                width, height = old_size
                if not all(math.isfinite(v) and v > 0 for v in old_size) or width * height * scale ** 2 > MAX_RENDER_PIXELS:
                    return None
                return _page_image(before, scale), _page_image(after, scale)
        except (pdfium.PdfiumError, OSError, ValueError, IndexError):
            return None


def _components(mask: Image.Image, before: Image.Image, after: Image.Image) -> list[dict]:
    width, height = mask.size
    remaining = bytearray(mask.tobytes())
    old, new = before.convert("L").tobytes(), after.convert("L").tobytes()
    boxes = []
    for first in range(len(remaining)):
        if not remaining[first]:
            continue
        remaining[first] = 0
        queue = deque([first])
        left = right = first % width
        top = bottom = first // width
        count, added, removed = 0, False, False
        while queue:
            index = queue.popleft()
            y, x = divmod(index, width)
            count += 1
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            added |= old[index] - new[index] > DIFFERENCE_LEVEL
            removed |= new[index] - old[index] > DIFFERENCE_LEVEL
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not (dx or dy) or not (0 <= x + dx < width and 0 <= y + dy < height):
                        continue
                    neighbor = index + dy * width + dx
                    if remaining[neighbor]:
                        remaining[neighbor] = 0
                        queue.append(neighbor)
        boxes.append({"box": (left, top, right + 1, bottom + 1), "count": count,
                      "added": added, "removed": removed})
    return boxes


def _near(a: tuple, b: tuple, distance: float) -> bool:
    dx = max(0, a[0] - b[2], b[0] - a[2])
    dy = max(0, a[1] - b[3], b[1] - a[3])
    return dx * dx + dy * dy <= distance * distance


def _merge(boxes: list[dict], distance: float) -> list[dict]:
    groups = []
    for component in boxes:
        current = dict(component)
        while True:
            neighbor = next((other for other in groups if _near(current["box"], other["box"], distance)), None)
            if neighbor is None:
                break
            groups.remove(neighbor)
            a, b = current["box"], neighbor["box"]
            current["box"] = min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])
            current["added"] |= neighbor["added"]
            current["removed"] |= neighbor["removed"]
        groups.append(current)
    return sorted(groups, key=lambda item: (item["box"][1], item["box"][0]))


def _regions_from_images(before: Image.Image, after: Image.Image, scale: float) -> list[m.DiffRegion]:
    mask = ImageChops.difference(before, after).convert("L").point(lambda value: 255 if value > DIFFERENCE_LEVEL else 0)
    candidates = [item for item in _components(mask, before, after)
                  if item["count"] >= MIN_COMPONENT_AREA_POINTS2 * scale ** 2]
    merged = _merge(candidates, MERGE_DISTANCE_POINTS * scale)
    width, height = before.size
    margin = CONTEXT_MARGIN_POINTS * scale
    regions = []
    for item in merged:
        left, top, right, bottom = item["box"]
        left, top = max(0, left - margin), max(0, top - margin)
        right, bottom = min(width, right + margin), min(height, bottom + margin)
        kind = "added" if item["added"] and not item["removed"] else "removed" if item["removed"] and not item["added"] else "moved"
        regions.append(m.DiffRegion(x=left / width, y=top / height, w=(right - left) / width,
                                    h=(bottom - top) / height, kind=kind, label=None))
    return regions


def regions(before_pdf, after_pdf) -> list[m.DiffRegion] | None:
    """Return changed areas, [] for identical first pages, or None when the pages cannot be compared."""
    pages = _pages(before_pdf, after_pdf)
    return _regions_from_images(*pages, scale=DPI / 72) if pages is not None else None


def compare(before_pdf, after_pdf, *, diff_id: str, sheet: str, title: str,
            from_rev: str, to_rev: str) -> m.DrawingDiff | None:
    pages = _pages(before_pdf, after_pdf)
    if pages is None:
        return None
    before, after = pages
    found = _regions_from_images(before, after, scale=DPI / 72)
    out = config.data_dir() / "files" / "diffs" / diff_id
    out.mkdir(parents=True, exist_ok=True)
    before.save(out / "before.png")
    after.save(out / "after.png")
    overlay = after.copy()
    selection = Image.new("L", after.size, 0)
    selected = ImageDraw.Draw(selection)
    for region in found:
        selected.rectangle((round(region.x * after.width), round(region.y * after.height),
                            round((region.x + region.w) * after.width), round((region.y + region.h) * after.height)), fill=255)
    old_ink = ImageChops.subtract(after.convert("L"), before.convert("L")).point(lambda value: 255 if value > DIFFERENCE_LEVEL else 0)
    new_ink = ImageChops.subtract(before.convert("L"), after.convert("L")).point(lambda value: 255 if value > DIFFERENCE_LEVEL else 0)
    overlay.paste((198, 40, 40), mask=ImageChops.multiply(old_ink, selection))
    overlay.paste((27, 122, 61), mask=ImageChops.multiply(new_ink, selection))
    pen = ImageDraw.Draw(overlay)
    width, height = overlay.size
    for region in found:
        pen.rectangle((round(region.x * width), round(region.y * height),
                       min(width - 1, round((region.x + region.w) * width)),
                       min(height - 1, round((region.y + region.h) * height))), outline=(255, 106, 0), width=2)
    overlay.save(out / "overlay.png")
    base = f"/media/files/diffs/{diff_id}"
    return m.DrawingDiff(id=diff_id, sheet=sheet, title=title, from_rev=from_rev, to_rev=to_rev,
                         before_url=f"{base}/before.png", after_url=f"{base}/after.png", overlay_url=f"{base}/overlay.png",
                         before_geometry_url=None, after_geometry_url=None, regions=found, summary=SUMMARY)
