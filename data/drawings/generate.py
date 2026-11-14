"""Generate the labelled synthetic drawing set from revision geometry."""
import argparse
import copy
import json
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
import reportlab
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


SEED = 20261113
WIDTH, HEIGHT = 22000, 13000
PIXELS_PER_MM = 0.1
COMPARISON_BOUNDS = {"x": 0, "y": 1800, "w": WIDTH, "h": 9600}
FONT_PATH = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"


def wall(key, x1, y1, x2, y2, kind="interior", thickness=150):
    return dict(id=key, x1=x1, y1=y1, x2=x2, y2=y2, thickness=thickness, kind=kind)


def baseline(sheet, revision):
    return {
        "sheet": sheet, "revision": revision, "units": "mm",
        "width": WIDTH, "height": HEIGHT, "wall_height": 2700,
        "walls": [
            wall("ext-n", 2000, 2500, 20000, 2500, "exterior", 250),
            wall("ext-e", 20000, 2500, 20000, 10500, "exterior", 250),
            wall("ext-s", 2000, 10500, 20000, 10500, "exterior", 250),
            wall("ext-w", 2000, 2500, 2000, 10500, "exterior", 250),
            wall("party-n", 11000, 2500, 11000, 6000),
            wall("party-s", 11000, 7000, 11000, 10500),
            wall("corridor-n", 2000, 6000, 20000, 6000),
            wall("corridor-s", 2000, 7000, 20000, 7000),
            wall("p-3a", 6000, 2500, 6000, 4700, "partition", 100),
            wall("p-3b", 11000, 3750, 20000, 3750, "partition", 100),
            wall("p-3c", 6000, 8300, 7500, 8300, "partition", 100),
            wall("p-3d", 16000, 9000, 17500, 9000, "partition", 100),
        ],
        "openings": [
            {"wall": "ext-n", "offset": 1600, "width": 1800, "kind": "window"},
            {"wall": "ext-n", "offset": 11600, "width": 1800, "kind": "window"},
            {"wall": "ext-s", "offset": 1600, "width": 1800, "kind": "window"},
            {"wall": "ext-s", "offset": 11600, "width": 1800, "kind": "window"},
            {"wall": "corridor-n", "offset": 1700, "width": 900, "kind": "door"},
            {"wall": "corridor-n", "offset": 11600, "width": 900, "kind": "door"},
            {"wall": "corridor-s", "offset": 1700, "width": 900, "kind": "door"},
            {"wall": "corridor-s", "offset": 11600, "width": 900, "kind": "door"},
            {"wall": "p-3b", "offset": 600, "width": 900, "kind": "door"},
        ],
        "rooms": [
            {"label": "3A", "x": 7800, "y": 4900},
            {"label": "3B", "x": 15500, "y": 5300},
            {"label": "3C", "x": 7800, "y": 9700},
            {"label": "3D", "x": 15500, "y": 8100},
            {"label": "LEVEL 3 CORRIDOR", "x": 10400, "y": 6500},
        ],
        "changed": [],
    }


def geometries():
    architectural = baseline("A-201", "B")
    revised = copy.deepcopy(architectural)
    revised["revision"] = "C"
    revised["changed"] = ["p-3b"]
    partition = next(w for w in revised["walls"] if w["id"] == "p-3b")
    partition["y1"] = partition["y2"] = 3450

    electrical = baseline("E-201", "A")
    electrical_revised = copy.deepcopy(electrical)
    electrical_revised["revision"] = "B"
    electrical_revised["changed"] = ["p-3a", "p-3c", "p-3d"]
    for item in electrical_revised["walls"]:
        if item["id"] == "p-3a":
            item["x1"] += 250
            item["x2"] += 250
        elif item["id"] in {"p-3c", "p-3d"}:
            item["y1"] += 250
            item["y2"] += 250
    return architectural, revised, electrical, electrical_revised


def render(geometry_path, png_path, pdf_path):
    """Read the persisted contract geometry and draw both sheet formats."""
    geometry = json.loads(Path(geometry_path).read_text(encoding="utf-8"))
    width, height = geometry["width"], geometry["height"]
    image = Image.new("RGB", (round(width * PIXELS_PER_MM), round(height * PIXELS_PER_MM)), "white")
    pen = ImageDraw.Draw(image)

    def xy(x, y):
        return round(x * PIXELS_PER_MM), round(y * PIXELS_PER_MM)

    def line(start, end, fill="#252525", weight=20):
        pen.line([xy(*start), xy(*end)], fill=fill, width=max(1, round(weight * PIXELS_PER_MM)))

    def text(x, y, value, size=220, anchor="la"):
        font = ImageFont.truetype(str(FONT_PATH), round(size * PIXELS_PER_MM))
        pen.text(xy(x, y), value, fill="#252525", font=font, anchor=anchor)

    pen.rectangle([xy(400, 400), xy(width - 400, height - 400)], outline="#252525", width=2)
    reference = random.Random(SEED).randrange(1000, 9999)
    text(800, 700, "MAPLE COURT", 440)
    text(800, 1280, f"LEVEL 03  /  {'PARTITION PLAN' if geometry['sheet'] == 'A-201' else 'ELECTRICAL COORDINATION'}  /  MC-{reference}", 220)
    text(width - 800, 700, f"{geometry['sheet']}  REV {geometry['revision']}", 400, "ra")
    text(width - 800, 1280, "DEMO DATA  /  NOT FOR CONSTRUCTION", 220, "ra")
    line((400, 1750), (width - 400, 1750))

    text(11000, 2100, "18 000 mm", 200, "ma")
    line((2000, 2350), (20000, 2350), "#777777", 10)
    line((2000, 2250), (2000, 2420), "#777777", 10)
    line((20000, 2250), (20000, 2420), "#777777", 10)
    for room in geometry["rooms"]:
        text(room["x"], room["y"], room["label"], 300 if len(room["label"]) < 4 else 200, "mm")
    walls = {item["id"]: item for item in geometry["walls"]}
    for item in walls.values():
        line((item["x1"], item["y1"]), (item["x2"], item["y2"]), weight=item["thickness"])
    for opening in geometry["openings"]:
        item = walls[opening["wall"]]
        dx, dy = item["x2"] - item["x1"], item["y2"] - item["y1"]
        length = (dx * dx + dy * dy) ** 0.5
        ux, uy = dx / length, dy / length
        start = (item["x1"] + ux * opening["offset"], item["y1"] + uy * opening["offset"])
        end = (start[0] + ux * opening["width"], start[1] + uy * opening["width"])
        line(start, end, "white", item["thickness"] + 20)
        if opening["kind"] == "window":
            line(start, end, "#777777", 30)
        else:
            tip = (start[0] - uy * opening["width"], start[1] + ux * opening["width"])
            line(start, tip, weight=20)
            pen.arc([xy(start[0] - opening["width"], start[1] - opening["width"]),
                     xy(start[0] + opening["width"], start[1] + opening["width"])],
                    0, 90, fill="#777777", width=1)

    line((400, 11400), (width - 400, 11400))
    text(800, 11700, "SYNTHETIC PROJECT  /  ALL DIMENSIONS IN mm", 200)
    text(800, 12100, "Exterior 250  /  Interior 150  /  Partition 100  /  Wall height 2700", 180)
    line((15500, 12250), (20500, 12250), weight=40)
    for x in [15500, 18000, 20500]:
        line((x, 12150), (x, 12350), weight=20)
    text(15500, 11800, "0", 180)
    text(18000, 11800, "2.5", 180, "ma")
    text(20500, 11800, "5 m", 180, "ra")
    text(width - 800, 12350, "PDF 1:100  /  PNG 100 px per metre", 180, "ra")

    metadata = PngImagePlugin.PngInfo()
    for key, value in {"demo_data": "DEMO DATA", "sheet": geometry["sheet"], "revision": geometry["revision"], "seed": str(SEED)}.items():
        metadata.add_text(key, value)
    image.save(png_path, pnginfo=metadata, optimize=False, compress_level=9, dpi=(254, 254))
    page_size = (width / 100 / 25.4 * 72, height / 100 / 25.4 * 72)
    document = canvas.Canvas(str(pdf_path), pagesize=page_size, invariant=1, pageCompression=1)
    document.setTitle(f"DEMO DATA | {geometry['sheet']} Rev {geometry['revision']} | Maple Court")
    document.setAuthor("Maple Court")
    document.setSubject("Synthetic drawing at 1:100, not for construction")
    document.drawImage(ImageReader(image), 0, 0, width=page_size[0], height=page_size[1])
    document.showPage()
    document.save()


def changed_region(before, after, key):
    old = next(w for w in before["walls"] if w["id"] == key)
    new = next(w for w in after["walls"] if w["id"] == key)
    # Include a door leaf wherever an opening travels with a wall.
    margin = max([200] + [o["width"] + 200 for o in after["openings"] if o["wall"] == key])
    x = min(old["x1"], old["x2"], new["x1"], new["x2"]) - margin
    y = min(old["y1"], old["y2"], new["y1"], new["y2"]) - margin
    right = max(old["x1"], old["x2"], new["x1"], new["x2"]) + margin
    bottom = max(old["y1"], old["y2"], new["y1"], new["y2"]) + margin
    box = dict(x=x, y=y, w=right - x, h=bottom - y)
    unit = key[2:].upper()
    dx, dy = new["x1"] - old["x1"], new["y1"] - old["y1"]
    direction = ("east" if dx > 0 else "west") if dx else ("south" if dy > 0 else "north")
    return {
        "wall_ids": [key], "unit": unit,
        "description": f"Unit {unit} partition moved {abs(dx) + abs(dy)} mm {direction}",
        "bbox_mm": box,
        "bbox": dict(x=x / WIDTH, y=y / HEIGHT, w=box["w"] / WIDTH, h=box["h"] / HEIGHT),
        "kind": "moved",
    }


def generate(output):
    """Write the four revision folders and the design-change manifest."""
    output = Path(output)
    revisions = geometries()
    for geometry in revisions:
        folder = output / geometry["sheet"] / geometry["revision"]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "geometry.json"
        path.write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8", newline="\n")
        render(path, folder / "sheet.png", folder / "sheet.pdf")
    manifest = {"seed": SEED, "demo_data": True, "comparison_bounds_mm": COMPARISON_BOUNDS, "pairs": []}
    for before, after in [(revisions[0], revisions[1]), (revisions[2], revisions[3])]:
        sheet = before["sheet"]
        manifest["pairs"].append({
            "sheet": sheet, "from_rev": before["revision"], "to_rev": after["revision"],
            "before": f"{sheet}/{before['revision']}", "after": f"{sheet}/{after['revision']}",
            "regions": [changed_region(before, after, key) for key in after["changed"]],
        })
    (output / "changes.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    arguments = parser.parse_args()
    generate(arguments.output)
    print(f"Generated 4 revisions (PDF, PNG, geometry) and changes.json in {arguments.output}")
