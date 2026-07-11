"""Reproduce the thesis section 4.3 2023 component total from its published inputs."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from subsidence_water_carbon import calculate_components, calculate_invest_replacement  # noqa: E402
from project_validator import validate  # noqa: E402


components = calculate_components(
    water_volume_m3=715100,
    water_carbon_density_g_c_m3=26.25,
    aquatic_vegetation_area_ha=44.57,
    aquatic_vegetation_carbon_density_t_c_ha=0.46,
    bottom_sediment_area_ha=51.28,
    bottom_sediment_carbon_density_t_c_ha=62.42,
)
assert abs(components["subsidence_water_composite_carbon_t_c"] - 3240.17) < 0.01, components
assert abs(calculate_invest_replacement(
    invest_total_carbon_t_c=1000,
    invest_subsidence_water_carbon_t_c=100,
    composite_carbon_t_c=200,
) - 1100) < 1e-9
project_report = validate(ROOT / "tests" / "fixtures" / "local_project" / "subsidence_water_project.json")
assert project_report["status"] == "valid", project_report
print(round(components["subsidence_water_composite_carbon_t_c"], 2))
