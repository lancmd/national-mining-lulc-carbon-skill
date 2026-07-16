"""Compile per-scenario Carbon and Annual Water Yield datastacks from one project."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_workflow import compile_workflow  # noqa: E402


with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as temporary:
    root = Path(temporary)
    data = root / "data"; data.mkdir()
    for name in ("lulc_1.tif", "lulc_2.tif", "slope.tif"):
        (data / name).write_bytes(b"placeholder")
    (data / "carbon.csv").write_text("lucode,c_above,c_below,c_soil,c_dead\n1,1,1,1,0\n", encoding="utf-8")
    (data / "awy.json").write_text(json.dumps({"args": {"lulc_path": "old.tif", "n_workers": -1},
                                                  "model_name": "natcap.invest.annual_water_yield"}), encoding="utf-8")
    (data / "ecosystem.json").write_text(json.dumps({"schema_version": 2, "method": "minmax", "id_field": "unit_id",
        "passthrough_fields": ["scenario"], "criteria": [
            {"field": "carbon_storage_t_c", "direction": "benefit", "weight": 0.5},
            {"field": "water_yield_m3", "direction": "benefit", "weight": 0.5}], "normalization": {"bounds": {}}}), encoding="utf-8")
    project = {
        "schema_version": 2, "project_id": "invest-multimodel", "workspace": "runtime",
        "security": {"input_roots": ["data"], "output_root": "."},
        "inputs": {"historical_lulc": ["data/lulc_1.tif", "data/lulc_2.tif"], "driver_factors": {"slope": "data/slope.tif"},
                   "carbon_density": "data/carbon.csv", "imagery": [], "lulc_baseline": None},
        "classification": {"enabled": False},
        "plus": {"enabled": True, "baseline_year": 2020, "target_year": 2025, "scenarios": ["ND"]},
        "invest": {"enabled": True, "output_workspace": "outputs/invest", "models": {
            "carbon": {"enabled": True, "service_unit": "Mg C"},
            "annual_water_yield": {"enabled": True, "datastack_template": "data/awy.json",
                                    "expected_outputs": ["output/per_pixel/wyield_vol.tif"], "service_unit": "m3"},
        }},
        "subsidence_water": {"enabled": False}, "ecosystem_service": {"enabled": True, "method": "minmax", "config": "data/ecosystem.json",
                                                                            "analysis": {"geodetector_factor_fields": []}},
        "gis_outputs": {"enabled": False}, "validation": {"enabled": False},
    }
    path = root / "project.json"; path.write_text(json.dumps(project), encoding="utf-8")
    report = compile_workflow(path)
    job = json.loads(Path(report["workflow_job"]).read_text(encoding="utf-8"))
    stages = {item["id"]: item for item in job["stages"]}
    assert {"invest_carbon_ND", "invest_annual_water_yield_ND"}.issubset(stages)
    awy_stack = json.loads(Path(stages["invest_annual_water_yield_ND"]["datastack"]).read_text(encoding="utf-8"))
    assert awy_stack["args"]["lulc_path"].endswith("PLUS_ND.tif")
    scenario_inputs = stages["ecosystem_scenario_inputs"]["inputs"]
    assert any("tot_c_cur.tif" in item for item in scenario_inputs)
    assert any("wyield_vol.tif" in item for item in scenario_inputs)

print('{"status":"completed","checks":["per-scenario InVEST datastacks","annual water yield LULC substitution","ecosystem full service inputs"]}')
