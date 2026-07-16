"""Exercise task-specific project construction without unrelated inputs."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_builder import build  # noqa: E402
from project_validator import validate  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    for name in ("image_2020.tif", "image_2025.tif", "lulc_2020.tif", "lulc_2025.tif", "roi.gpkg", "carbon.csv",
                 "criteria.csv", "ecosystem.json", "base.aprx", "dem.tif"):
        (root / name).write_text("fixture", encoding="utf-8")
    imagery = [{"year": 2020, "path": str(root / "image_2020.tif")}, {"year": 2025, "path": str(root / "image_2025.tif")}]
    history = [{"year": 2020, "path": str(root / "lulc_2020.tif")}, {"year": 2025, "path": str(root / "lulc_2025.tif")}]
    modes = {
        "classification_only": {"imagery_periods": imagery, "training_roi": str(root / "roi.gpkg")},
        "lulc_change_analysis": {"historical_lulc_periods": history},
        "plus_only": {"historical_lulc_periods": history, "driver_factors": {"dem": str(root / "dem.tif")}},
        "invest_only": {"historical_lulc_periods": history, "carbon_density": str(root / "carbon.csv")},
        "ecosystem_service_only": {"ecosystem_criteria": str(root / "criteria.csv"), "ecosystem_config": str(root / "ecosystem.json")},
        "mapping_only": {"gis_outputs": {"aprx": str(root / "base.aprx"), "layout_name": "Layout", "png": "outputs/map.png",
                                         "layers": [{"path": "outputs/ready.tif", "path_scope": "workspace"}]}},
    }
    expected = {
        "classification_only": (True, False, False, False, False), "lulc_change_analysis": (False, False, False, False, False),
        "plus_only": (False, True, False, False, False), "invest_only": (False, False, True, False, False),
        "ecosystem_service_only": (False, False, False, True, False), "mapping_only": (False, False, False, False, True),
    }
    for task_type, values in modes.items():
        destination = root / task_type / "project.json"
        report = build(destination, task_type, "runtime", task_type=task_type, **values)
        project = json.loads(destination.read_text(encoding="utf-8"))
        actual = (project["classification"]["enabled"], project["plus"]["enabled"], project["invest"]["enabled"],
                  project["ecosystem_service"]["enabled"], project["gis_outputs"]["enabled"])
        assert report["task_type"] == task_type and actual == expected[task_type], (task_type, actual)
        if task_type == "mapping_only":
            assert validate(destination)["status"] == "valid", validate(destination)

print('{"status":"completed","checks":["task-specific project construction"]}')
