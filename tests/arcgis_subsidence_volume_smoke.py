"""Assert ArcGIS volume operation returns 90,000 m3 for a known synthetic raster."""

import csv
from pathlib import Path


path = Path(__file__).resolve().parents[1] / "outputs" / "arcgis_smoke" / "validation" / "water_volume.csv"
with path.open("r", encoding="utf-8-sig", newline="") as stream:
    row = next(csv.DictReader(stream))
assert abs(float(row["water_volume_m3"]) - 90000.0) < 1e-6, row
print(row["water_volume_m3"])
