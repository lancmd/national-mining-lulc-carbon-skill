"""Assert the ArcGIS thesis-4.3 operation produces expected component carbon values."""

import csv
from pathlib import Path


path = Path(__file__).resolve().parents[1] / "outputs" / "arcgis_smoke" / "validation" / "water_carbon.csv"
with path.open("r", encoding="utf-8-sig", newline="") as stream:
    row = next(csv.DictReader(stream))
assert abs(float(row["water_volume_m3"]) - 90000.0) < 1e-6, row
assert abs(float(row["aquatic_vegetation_area_ha"]) - 9.0) < 1e-6, row
assert abs(float(row["bottom_sediment_area_ha"]) - 9.0) < 1e-6, row
assert abs(float(row["water_carbon_t_c"]) - 90.0) < 1e-6, row
assert abs(float(row["aquatic_vegetation_carbon_t_c"]) - 90.0) < 1e-6, row
assert abs(float(row["bottom_sediment_carbon_t_c"]) - 900.0) < 1e-6, row
assert abs(float(row["subsidence_water_composite_carbon_t_c"]) - 1080.0) < 1e-6, row
print(row["subsidence_water_composite_carbon_t_c"])

empty_path = path.with_name("water_carbon_no_vegetation.csv")
with empty_path.open("r", encoding="utf-8-sig", newline="") as stream:
    empty = next(csv.DictReader(stream))
assert float(empty["aquatic_vegetation_area_ha"]) == 0.0, empty
assert float(empty["aquatic_vegetation_carbon_t_c"]) == 0.0, empty
