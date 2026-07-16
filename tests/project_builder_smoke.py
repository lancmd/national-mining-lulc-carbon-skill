"""Verify the agent-facing input builder emits the dated automation contract."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_builder import build  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    names = ["image_2020.tif", "image_2025.tif", "dem.tif", "boundary.shp", "carbon.csv", "roi.gpkg", "w.dat"]
    for name in names:
        (root / name).write_text("fixture", encoding="utf-8")
    target = root / "generated" / "project.json"
    result = build(target, "builder-smoke", "runtime", [{"year": 2020, "path": str(root / "image_2020.tif")},
                    {"year": 2025, "path": str(root / "image_2025.tif")}], {"dem": str(root / "dem.tif")},
                   str(root / "boundary.shp"), str(root / "carbon.csv"), w_dat=str(root / "w.dat"),
                   training_roi=str(root / "roi.gpkg"), w_dat_unit="mm", w_dat_convention="negative_down")
    project = json.loads(target.read_text(encoding="utf-8"))
    assert result["imagery_years"] == [2020, 2025]
    assert project["classification"]["engine"] == "envi"
    assert project["plus"]["scenarios"] == ["ND", "UD", "EP", "RE"]
    direct = build(root / "generated" / "depth-project.json", "builder-depth", "runtime-depth",
                   [{"year": 2020, "path": str(root / "image_2020.tif")}, {"year": 2025, "path": str(root / "image_2025.tif")}],
                   {"dem": str(root / "dem.tif")}, str(root / "boundary.shp"), str(root / "carbon.csv"),
                   model_package=str(root / "model"), subsidence_depth_raster=str(root / "dem.tif"))
    depth_project = json.loads(Path(direct["project_file"]).read_text(encoding="utf-8"))
    assert depth_project["inputs"]["subsidence_depth_raster"] == str((root / "dem.tif").resolve())
print('{"status":"completed","checks":["agent input builder","dated imagery contract"]}')
