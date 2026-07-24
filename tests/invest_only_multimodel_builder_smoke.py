"""Build an invest_only project with Water Yield and Habitat Quality but no Carbon model."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_builder import build  # noqa: E402
from project_validator import validate  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    lulc = root / "lulc_2025.tif"; lulc.write_bytes(b"fixture")
    for name, model in (("awy.json", "annual_water_yield"), ("habitat.json", "habitat_quality")):
        (root / name).write_text(json.dumps({"model_name": f"natcap.invest.{model}", "args": {"lulc_path": "old.tif"}}), encoding="utf-8")
    project_file = root / "project.json"
    report = build(project_file, "invest-services", "runtime", task_type="invest_only",
                   historical_lulc_periods=[{"year": 2025, "path": str(lulc)}], invest_models={
                       "annual_water_yield": {"enabled": True, "datastack_template": str(root / "awy.json"),
                                               "expected_outputs": ["output/per_pixel/wyield_vol.tif"], "service_unit": "m3"},
                       "habitat_quality": {"enabled": True, "datastack_template": str(root / "habitat.json"),
                                           "expected_outputs": ["quality.tif"], "service_unit": "index", "service_aggregation": "mean"},
                   })
    payload = json.loads(project_file.read_text(encoding="utf-8"))
    assert report["pending_inputs"] == [], report
    assert set(payload["invest"]["models"]) == {"annual_water_yield", "habitat_quality"}, payload["invest"]
    assert payload["inputs"]["carbon_density"] is None
    assert validate(project_file)["status"] == "valid", validate(project_file)

print('{"status":"completed","checks":["invest_only multiple selected models"]}')
