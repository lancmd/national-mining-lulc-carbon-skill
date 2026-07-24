"""Verify the builder can express every enabled full-chain module from MCP inputs."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_builder import build  # noqa: E402
from project_validator import validate  # noqa: E402
from project_workflow import compile_workflow  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    for name in ("image_2020.tif", "image_2025.tif", "dem.tif", "depth.tif", "roi.gpkg", "boundary.gpkg",
                 "water.gpkg", "samples.csv", "layout.aprx"):
        (root / name).write_bytes(b"fixture")
    (root / "carbon.csv").write_text("lucode,c_above,c_below,c_soil,c_dead\n1,1,1,1,0\n", encoding="utf-8")
    (root / "samples.csv").write_text("reference,prediction\n1,1\n", encoding="utf-8")
    (root / "ecosystem.json").write_text(json.dumps({"schema_version": 2, "method": "minmax", "id_field": "unit_id",
        "criteria": [{"field": "carbon_storage_t_c", "direction": "benefit", "weight": 1.0}], "normalization": {"bounds": {}}}), encoding="utf-8")
    report = build(root / "project.json", "full-chain-options", "runtime", task_type="full_chain",
                   imagery_periods=[{"year": 2020, "path": str(root / "image_2020.tif")},
                                    {"year": 2025, "path": str(root / "image_2025.tif")}],
                   driver_factors={"dem": str(root / "dem.tif")}, mine_boundary=str(root / "boundary.gpkg"),
                   carbon_density=str(root / "carbon.csv"), training_roi=str(root / "roi.gpkg"),
                   subsidence_depth_raster=str(root / "depth.tif"),
                   accuracy_config={"validation_samples": str(root / "samples.csv")},
                   ecosystem_config=str(root / "ecosystem.json"),
                   subsidence_water_boundary=str(root / "water.gpkg"), elevation_vertical_datum="EGM96",
                   water_level_vertical_datum="EGM96", water_surface_elevation_m=100.0,
                   subsidence_water_config={"mode": "estimate_volume", "output_depth_raster": "outputs/subsidence/depth.tif",
                                             "output_volume_table": "outputs/subsidence/volume.csv"},
                   gis_outputs={"aprx": str(root / "layout.aprx"), "layout_name": "Layout", "png": "outputs/maps/final.png",
                                "layers": [{"source": "stage_output", "stage_id": "invest_carbon_ND", "output_index": 0,
                                            "name": "Carbon ND", "kind": "continuous"}]})
    payload = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert report["pending_inputs"] == [], report
    assert payload["classification"]["accuracy"]["enabled"] is True
    assert payload["ecosystem_service"]["enabled"] is True
    assert payload["subsidence_water"]["enabled"] is True
    assert payload["gis_outputs"]["enabled"] is True
    assert validate(root / "project.json")["status"] == "valid", validate(root / "project.json")
    compiled = compile_workflow(root / "project.json")
    assert {"lulc_accuracy", "subsidence_water", "ecosystem_service", "map_layout"}.issubset(compiled["stage_ids"]), compiled

    incomplete = build(root / "incomplete.json", "full-chain-incomplete", "runtime-incomplete", task_type="full_chain",
                       imagery_periods=[{"year": 2020, "path": str(root / "image_2020.tif")},
                                        {"year": 2025, "path": str(root / "image_2025.tif")}],
                       driver_factors={"dem": str(root / "dem.tif")}, mine_boundary=str(root / "boundary.gpkg"),
                       carbon_density=str(root / "carbon.csv"), training_roi=str(root / "roi.gpkg"),
                       subsidence_depth_raster=str(root / "depth.tif"))
    assert {"independent_lulc_validation_samples", "ecosystem_service_config", "gis_layout_config"}.issubset(incomplete["pending_inputs"]), incomplete

print('{"status":"completed","checks":["full-chain builder options","validation and ecosystem configuration","subsidence and GIS configuration"]}')
