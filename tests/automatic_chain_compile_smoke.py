"""Ensure dated imagery automatically feeds Sankey, aligned inputs and PLUS."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_workflow import compile_workflow  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    for name in ("image_2020.tif", "image_2025.tif", "dem.tif", "w.dat", "workface.geojson"):
        (root / name).write_bytes(b"fixture")
    (root / "carbon.csv").write_text("lucode,c_above,c_below,c_soil,c_dead\n1,0,0,0,0\n2,0,0,0,0\n3,0,0,0,0\n4,0,0,0,0\n5,0,0,0,0\n6,0,0,0,0\n7,0,0,0,0\n", encoding="utf-8")
    package = root / "model"; package.mkdir(); (package / "model_config.json").write_text("{}", encoding="utf-8")
    project = {"schema_version": 2, "project_id": "automatic-chain", "workspace": "runtime",
        "security": {"input_roots": [str(root)], "output_root": "runtime"},
        "inputs": {"imagery_periods": [{"year": 2020, "path": str(root / "image_2020.tif")}, {"year": 2025, "path": str(root / "image_2025.tif")}],
                   "imagery": [], "model_package": str(package), "carbon_density": str(root / "carbon.csv"),
                   "subsidence_w_dat": str(root / "w.dat"), "workface_boundary": str(root / "workface.geojson"), "driver_factors": {"dem": str(root / "dem.tif")}},
        "classification": {"enabled": True, "engine": "pytorch", "scheme": "high_water_coal_7class"},
        "plus": {"enabled": True, "baseline_year": 2025, "target_year": 2030, "scenarios": ["ND", "UD", "EP", "RE"],
                 "resource_extraction": {"core_driver": "subsidence_depth", "core_driver_input": "inputs.subsidence_depth_raster",
                    "core_driver_unit": "m", "core_driver_convention": "positive_down", "requires_master_grid_alignment": True,
                    "additional_driver_factors": ["dem"], "w_dat_preprocessing": {"source_unit": "mm", "source_convention": "negative_down", "max_interpolation_distance_m": 300}}},
        "invest": {"enabled": True, "models": {"carbon": {"enabled": True}}}, "subsidence_water": {"enabled": False},
        "ecosystem_service": {"enabled": False}, "gis_outputs": {"enabled": False}}
    project_file = root / "project.json"; project_file.write_text(json.dumps(project), encoding="utf-8")
    report = compile_workflow(project_file); identifiers = set(report["stage_ids"])
    assert {"classification_pytorch_2020", "classification_pytorch_2025", "align_lulc_2020", "historical_lulc_preflight",
            "lulc_sankey_2020_2025", "derive_terrain", "align_driver_dem", "standardise_w_dat", "rasterise_w_dat",
            "plus_input_preflight", "plus_ND", "plus_RE", "invest_carbon_ND", "invest_carbon_RE"}.issubset(identifiers), identifiers
print('{"status":"completed","checks":["multi-date LULC", "Sankey", "w.dat to RE", "PLUS to InVEST"]}')
