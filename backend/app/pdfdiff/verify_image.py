"""Offline runtime check for the packaged renderer and demo data."""
import json
import os
import tempfile

from PIL import Image

from app import demodata
from app.core import config
from app.live import directory
from app.replay import real as replay
from .real import compare


def main():
    data = demodata.load()
    assert data.source == "data/project" and len(data.project.units) == 24
    assert {"1H", "3H"}.issubset({task.unit for task in data.plan.tasks})
    assert directory.lookup("Marco Ruiz").crew == "Framing crew"
    assert {"e18", "e27", "e58"}.issubset({event.id for event in replay.events()})
    drawing = config.ROOT / "data" / "drawings" / "A-201"
    with tempfile.TemporaryDirectory(prefix="pdf-image-check-") as temporary:
        previous = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = temporary
        try:
            diff = compare(drawing / "B" / "sheet.pdf", drawing / "C" / "sheet.pdf",
                           diff_id="image-check", sheet="A-201", title="Image check", from_rev="B", to_rev="C")
            assert diff is not None and len(diff.regions) == 1
            assert diff.before_geometry_url is None and diff.after_geometry_url is None
            with Image.open(config.data_dir() / "files" / "diffs" / diff.id / "overlay.png") as image:
                assert image.width > 0 and image.height > 0
                size = image.size
        finally:
            if previous is None:
                os.environ.pop("DATA_DIR", None)
            else:
                os.environ["DATA_DIR"] = previous
    print(json.dumps({"project_source": data.source, "units": len(data.project.units),
                      "replay": "loaded", "pdf_regions": len(diff.regions), "overlay_size": size}))


if __name__ == "__main__":
    main()
