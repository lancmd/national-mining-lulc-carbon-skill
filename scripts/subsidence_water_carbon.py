#!/usr/bin/env python3
"""Calculate the thesis 4.3 subsidence-water carbon components with explicit units."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def nonnegative(name: str, value: float | int) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def calculate_components(*, water_volume_m3: float, water_carbon_density_g_c_m3: float,
                         aquatic_vegetation_area_ha: float,
                         aquatic_vegetation_carbon_density_t_c_ha: float,
                         bottom_sediment_area_ha: float,
                         bottom_sediment_carbon_density_t_c_ha: float) -> dict[str, float]:
    """Implement equations 4.7, 4.9, and the three-component total in thesis section 4.3.

    Water density is g C/m3, so the conversion to t C is division by 1,000,000.
    Vegetation and sediment densities are t C/ha (numerically equal to Mg C/ha).
    """
    volume = nonnegative("water_volume_m3", water_volume_m3)
    water_density = nonnegative("water_carbon_density_g_c_m3", water_carbon_density_g_c_m3)
    vegetation_area = nonnegative("aquatic_vegetation_area_ha", aquatic_vegetation_area_ha)
    vegetation_density = nonnegative(
        "aquatic_vegetation_carbon_density_t_c_ha", aquatic_vegetation_carbon_density_t_c_ha)
    sediment_area = nonnegative("bottom_sediment_area_ha", bottom_sediment_area_ha)
    sediment_density = nonnegative("bottom_sediment_carbon_density_t_c_ha", bottom_sediment_carbon_density_t_c_ha)

    water_carbon = volume * water_density / 1_000_000.0
    vegetation_carbon = vegetation_area * vegetation_density
    sediment_carbon = sediment_area * sediment_density
    return {
        "water_carbon_t_c": water_carbon,
        "aquatic_vegetation_carbon_t_c": vegetation_carbon,
        "bottom_sediment_carbon_t_c": sediment_carbon,
        "subsidence_water_composite_carbon_t_c": water_carbon + vegetation_carbon + sediment_carbon,
    }


def calculate_invest_replacement(*, invest_total_carbon_t_c: float,
                                 invest_subsidence_water_carbon_t_c: float,
                                 composite_carbon_t_c: float) -> float:
    """Replace, rather than double-count, InVEST's area-based subsidence-water carbon."""
    total = nonnegative("invest_total_carbon_t_c", invest_total_carbon_t_c)
    invest_water = nonnegative("invest_subsidence_water_carbon_t_c", invest_subsidence_water_carbon_t_c)
    composite = nonnegative("composite_carbon_t_c", composite_carbon_t_c)
    if invest_water > total:
        raise ValueError("invest_subsidence_water_carbon_t_c cannot exceed invest_total_carbon_t_c")
    return total - invest_water + composite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON values using the function argument names")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args()
    payload: dict[str, Any] = json.loads(args.input.read_text(encoding="utf-8-sig"))
    result = calculate_components(
        water_volume_m3=payload["water_volume_m3"],
        water_carbon_density_g_c_m3=payload["water_carbon_density_g_c_m3"],
        aquatic_vegetation_area_ha=payload["aquatic_vegetation_area_ha"],
        aquatic_vegetation_carbon_density_t_c_ha=payload["aquatic_vegetation_carbon_density_t_c_ha"],
        bottom_sediment_area_ha=payload["bottom_sediment_area_ha"],
        bottom_sediment_carbon_density_t_c_ha=payload["bottom_sediment_carbon_density_t_c_ha"],
    )
    if "invest_total_carbon_t_c" in payload or "invest_subsidence_water_carbon_t_c" in payload:
        result["enhanced_invest_total_carbon_t_c"] = calculate_invest_replacement(
            invest_total_carbon_t_c=payload["invest_total_carbon_t_c"],
            invest_subsidence_water_carbon_t_c=payload["invest_subsidence_water_carbon_t_c"],
            composite_carbon_t_c=result["subsidence_water_composite_carbon_t_c"],
        )
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
