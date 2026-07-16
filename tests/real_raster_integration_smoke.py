"""Exercise the portable spatial parts of the end-to-end workflow on real tiny rasters."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_workflow import compile_workflow  # noqa: E402
from analysis_validation import validate_subsidence_water  # noqa: E402
from scenario_service_table import build  # noqa: E402
from workflow_agent import JobRunner  # noqa: E402


def command(*args: object) -> None:
    process = subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, check=False)
    assert process.returncode == 0, process.stdout


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    profile = {"driver": "GTiff", "width": 6, "height": 6, "count": 1, "crs": "EPSG:32650",
               "transform": from_origin(500000, 3700060, 10, 10), "nodata": 0}
    classes = np.array([
        [1, 1, 1, 2, 2, 2], [1, 1, 2, 2, 2, 1], [1, 2, 1, 2, 1, 2],
        [3, 3, 3, 4, 4, 4], [3, 4, 3, 4, 4, 3], [3, 3, 4, 4, 3, 4],
    ], dtype="uint8")
    native = root / "lulc_10m.tif"
    with rasterio.open(native, "w", dtype="uint8", **profile) as sink:
        sink.write(classes, 1)
    master = root / "master_30m.tif"
    command(ROOT / "scripts" / "raster_grid.py", "--input", native, "--output", master, "--cell-size-m", 30,
            "--kind", "categorical", "--resampling", "majority")
    with rasterio.open(master) as source:
        assert (source.width, source.height) == (2, 2)
        assert source.read(1).tolist() == [[1, 2], [3, 4]]
        assert abs(source.transform.a) == 30

    continuous = root / "temperature_10m.tif"
    with rasterio.open(continuous, "w", dtype="float32", **profile) as sink:
        sink.write(np.arange(36, dtype="float32").reshape(1, 6, 6))
    aligned = root / "temperature_30m.tif"
    command(ROOT / "scripts" / "raster_grid.py", "--input", continuous, "--master", master, "--output", aligned,
            "--kind", "continuous", "--resampling", "bilinear")
    assert json.loads((aligned.with_suffix(".tif.metadata.json")).read_text(encoding="utf-8"))["resampling"] == "bilinear"

    points = root / "depth.csv"
    points.write_text("x,y,subsidence_depth_m\n500005,3700055,2\n", encoding="utf-8")
    # A one-cell polygon proves interpolation does not escape the local workface.
    scope = root / "scope.geojson"
    scope.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [[[500000, 3700030], [500030, 3700030], [500030, 3700060], [500000, 3700060], [500000, 3700030]]]}}]}), encoding="utf-8")
    depth = root / "depth_30m.tif"
    command(ROOT / "scripts" / "wdat_rasterize.py", "--points", points, "--master", master, "--output", depth,
            "--fill-nearest", "--scope-vector", scope, "--max-distance-m", 45)
    with rasterio.open(depth) as source:
        data = source.read(1)
        assert int((data != -9999).sum()) == 1, data
    report = json.loads(depth.with_suffix(".tif.metadata.json").read_text(encoding="utf-8"))
    assert report["interpolation"] == "nearest_PIM_sample_within_scope_and_distance"

    classification_evidence = root / "subsidence_classification.json"
    command(ROOT / "scripts" / "subsidence_water_evidence.py", "--lulc", master, "--water-code", 1, "--output", classification_evidence)
    assert validate_subsidence_water(json.loads(classification_evidence.read_text(encoding="utf-8")))["status"] == "completed"

    nodata = root / "all_nodata.tif"
    with rasterio.open(nodata, "w", dtype="float32", **profile) as sink:
        sink.write(np.full((1, 6, 6), -9999, dtype="float32")); sink.nodata = -9999
    try:
        build({"ND": {"water": nodata}}, None, root / "invalid.csv")
        raise AssertionError("all-NoData ecosystem service was converted to zero")
    except ValueError as error:
        assert "no valid pixels" in str(error)

    geo = root / "geodetector.csv"
    command(ROOT / "scripts" / "geodetector_spatial_samples.py", "--target", aligned, "--target-field", "service",
            "--factor", f"lulc={master}", "--factor", f"temp={aligned}", "--output", geo, "--continuous-bins", 2)
    rows = list(csv.DictReader(geo.open(encoding="utf-8-sig")))
    assert rows and all(row["lulc"] and row["temp"].startswith("Q") for row in rows)

    carbon = root / "carbon.csv"
    carbon.write_text("lucode,c_above,c_below,c_soil,c_dead\n1,0,0,0,0\n2,0,0,0,0\n3,0,0,0,0\n4,0,0,0,0\n5,0,0,0,0\n6,0,0,0,0\n", encoding="utf-8")
    project = {"schema_version": 2, "project_id": "historical-carbon", "workspace": "runtime",
        "security": {"input_roots": [str(root)], "output_root": "runtime"},
        "inputs": {"lulc_baseline": str(native), "historical_lulc_periods": [{"year": 2020, "path": str(native)}, {"year": 2025, "path": str(native)}],
                   "carbon_density": str(carbon), "driver_factors": {}},
        "classification": {"enabled": False}, "plus": {"enabled": False}, "invest": {"enabled": True, "models": {"carbon": {"enabled": True}}},
        "subsidence_water": {"enabled": True, "mode": "classify_only", "water_code": 1}, "ecosystem_service": {"enabled": False}, "gis_outputs": {"enabled": False}, "validation": {"enabled": False}}
    project_file = root / "project.json"; project_file.write_text(json.dumps(project), encoding="utf-8")
    compiled = compile_workflow(project_file)
    assert {"invest_carbon_2020", "invest_carbon_2025", "subsidence_water_classification_evidence"}.issubset(set(compiled["stage_ids"]))

    class FakePlusRunner(JobRunner):
        def run_plus(self, stage):  # type: ignore[no-untyped-def]
            return {"status": "completed" if Path(stage["outputs"][0]).exists() else "waiting_interactive"}

    workspace = root / "pause_workspace"; plus_raster = workspace / "outputs" / "PLUS_ND.tif"; final = workspace / "outputs" / "downstream.txt"
    job = {"schema_version": 1, "project_id": "plus-pause", "workspace": str(workspace),
           "security": {"input_roots": [str(root)], "output_root": str(workspace)}, "software": {}, "stages": [
               {"id": "plus_ND", "adapter": "plus", "enabled": True, "inputs": [], "outputs": [str(plus_raster)], "depends_on": []},
               {"id": "after_plus", "adapter": "command", "enabled": True, "inputs": [str(plus_raster)], "outputs": [str(final)],
                "command": [sys.executable, "-c", "from pathlib import Path; Path('outputs/downstream.txt').write_text('ok')"], "depends_on": ["plus_ND"]}]}
    job_path = root / "pause_job.json"; job_path.write_text(json.dumps(job), encoding="utf-8")
    first = FakePlusRunner(job_path); assert first.run() == 0
    assert first.state["workflow"]["status"] == "paused" and not final.exists()
    plus_raster.parent.mkdir(parents=True, exist_ok=True); plus_raster.write_bytes(b"adopted")
    second = FakePlusRunner(job_path); assert second.run() == 0 and final.is_file()

print('{"status":"completed","checks":["30m majority","continuous resampling","bounded w.dat","NoData","GeoDetector sampling","historical InVEST","PLUS pause-resume"]}')
