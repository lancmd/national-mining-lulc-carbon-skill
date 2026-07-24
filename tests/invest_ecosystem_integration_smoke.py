"""Run tiny Annual Water Yield and Habitat Quality jobs when local InVEST is available."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from workflow_agent import probe_software  # noqa: E402


def write_raster(path: Path, values: np.ndarray, *, dtype: str = "float32") -> None:
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1, dtype=dtype,
                       crs="EPSG:32650", transform=from_origin(500000, 3700060, 30, 30), nodata=-9999) as sink:
        sink.write(values.astype(dtype), 1)


invest = probe_software()["software"]["invest"]["path"]
if os.getenv("MAESA_RUN_LOCAL_INVEST_INTEGRATION") != "1":
    print(json.dumps({"status": "completed", "execution": "skipped", "reason": "set MAESA_RUN_LOCAL_INVEST_INTEGRATION=1 for local InVEST integration"}))
    raise SystemExit(0)
if not invest:
    print(json.dumps({"status": "completed", "execution": "skipped", "reason": "local InVEST is unavailable"}))
    raise SystemExit(0)

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    lulc = root / "lulc.tif"; write_raster(lulc, np.array([[1, 2], [1, 2]], dtype="int16"), dtype="int16")
    precip = root / "precip.tif"; write_raster(precip, np.full((2, 2), 1000.0, dtype="float32"))
    eto = root / "eto.tif"; write_raster(eto, np.full((2, 2), 500.0, dtype="float32"))
    root_depth = root / "root_depth.tif"; write_raster(root_depth, np.full((2, 2), 1000.0, dtype="float32"))
    pawc = root / "pawc.tif"; write_raster(pawc, np.full((2, 2), 0.2, dtype="float32"))
    threat = root / "road_threat.tif"; write_raster(threat, np.array([[1, 0], [0, 1]], dtype="int16"), dtype="int16")
    watershed = root / "watershed.geojson"
    watershed.write_text(json.dumps({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:32650"}}, "features": [{"type": "Feature", "properties": {"ws_id": 1},
        "geometry": {"type": "Polygon", "coordinates": [[[500000, 3700000], [500060, 3700000], [500060, 3700060],
        [500000, 3700060], [500000, 3700000]]]}}]}), encoding="utf-8")
    bio = root / "biophysical.csv"
    with bio.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["lucode", "root_depth", "Kc", "lulc_veg"])
        writer.writerows([[1, 500, 0.8, 1], [2, 800, 0.9, 1]])
    threats = root / "threats.csv"
    with threats.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["threat", "max_dist", "weight", "decay", "cur_path"])
        writer.writerow(["road", 1000, 1, "linear", threat])
    sensitivity = root / "sensitivity.csv"
    with sensitivity.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["lulc", "habitat", "road"])
        writer.writerows([[1, 1, 0.5], [2, 0.5, 0.8]])
    annual = root / "annual_water_yield.json"
    annual.write_text(json.dumps({"model_name": "natcap.invest.annual_water_yield", "invest_version": "3.12.1", "args": {
        "lulc_path": str(lulc), "precipitation_path": str(precip), "eto_path": str(eto),
        "depth_to_root_rest_layer_path": str(root_depth), "pawc_path": str(pawc), "watersheds_path": str(watershed),
        "biophysical_table_path": str(bio), "seasonality_constant": 8.1, "results_suffix": "smoke", "n_workers": -1,
    }}), encoding="utf-8")
    habitat = root / "habitat_quality.json"
    habitat.write_text(json.dumps({"model_name": "natcap.invest.habitat_quality", "invest_version": "3.12.1", "args": {
        "lulc_cur_path": str(lulc), "threats_table_path": str(threats), "sensitivity_table_path": str(sensitivity),
        "half_saturation_constant": 0.5, "results_suffix": "smoke", "n_workers": -1,
    }}), encoding="utf-8")
    for model, datastack, expected in (("annual_water_yield", annual, "output/per_pixel/wyield_smoke.tif"),
                                       ("habitat_quality", habitat, "quality_c_smoke.tif")):
        workspace = root / model
        process = subprocess.run([invest, "run", model, "-l", "-d", str(datastack), "-w", str(workspace)],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 errors="replace", check=False, timeout=300)
        assert process.returncode == 0, process.stdout
        assert (workspace / expected).is_file(), [str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file()]
print(json.dumps({"status": "completed", "checks": ["InVEST Annual Water Yield", "InVEST Habitat Quality"]}))
