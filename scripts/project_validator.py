#!/usr/bin/env python3
"""Validate a local mining-area analysis project before software execution."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


REQUIRED_CARBON_COLUMNS = {"lucode", "c_above", "c_below", "c_soil", "c_dead"}
VALID_ENGINES = {"envi", "pytorch", "provided_lulc"}
VALID_ECOSYSTEM_METHODS = {"minmax", "ahp"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def resolve(value: str | None, base: Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def required_path(label: str, value: str | None, base: Path, errors: list[str]) -> Path | None:
    path = resolve(value, base)
    if path is None or "replace_" in str(value):
        errors.append(f"missing required input: {label}")
    elif not path.exists():
        errors.append(f"input does not exist: {label} = {path}")
    return path


def validate_carbon_table(path: Path | None, errors: list[str]) -> None:
    if path is None or not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            header = set((csv.DictReader(stream).fieldnames or []))
        missing = REQUIRED_CARBON_COLUMNS - header
        if missing:
            errors.append(f"carbon density table misses columns: {', '.join(sorted(missing))}")
    except Exception as error:
        errors.append(f"cannot read carbon density table: {error}")


def validate(project_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    project = load_json(project_path)
    base = project_path.parent
    if project.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if not project.get("project_id") or project.get("project_id") == "replace_me":
        errors.append("project_id must be set")
    inputs = project.get("inputs", {})
    imagery = inputs.get("imagery")
    if not isinstance(imagery, list) or not imagery:
        errors.append("inputs.imagery must contain at least one local raster")
    else:
        for index, item in enumerate(imagery):
            required_path(f"imagery[{index}]", item, base, errors)
    required_path("roi", inputs.get("roi"), base, errors)
    required_path("mine_boundary", inputs.get("mine_boundary"), base, errors)
    carbon = required_path("carbon_density", inputs.get("carbon_density"), base, errors)
    validate_carbon_table(carbon, errors)

    classification = project.get("classification", {})
    if classification.get("enabled"):
        engine = classification.get("engine")
        if engine not in VALID_ENGINES:
            errors.append(f"classification.engine must be one of {sorted(VALID_ENGINES)}")
        if engine == "envi":
            required_path("training_roi", inputs.get("training_roi"), base, errors)
        elif engine == "pytorch":
            package = required_path("model_package", inputs.get("model_package"), base, errors)
            if package and package.is_dir() and not (package / "model_config.json").exists():
                errors.append("PyTorch model_package must contain model_config.json")
        elif engine == "provided_lulc":
            required_path("lulc_baseline", inputs.get("lulc_baseline"), base, errors)
        if classification.get("scheme") not in {"standard_6class", "high_water_coal_7class"}:
            errors.append("classification.scheme must be standard_6class or high_water_coal_7class")
    elif not inputs.get("lulc_baseline"):
        errors.append("provide lulc_baseline when classification is disabled")

    plus = project.get("plus", {})
    if plus.get("enabled"):
        factors = inputs.get("driver_factors", {})
        supplied = [key for key, value in factors.items() if value]
        if not supplied:
            errors.append("PLUS requires local driver_factors")
        if not plus.get("scenarios"):
            errors.append("PLUS requires at least one scenario")
        if plus.get("target_year", 0) <= plus.get("baseline_year", 0):
            errors.append("PLUS target_year must be later than baseline_year")
        for key in supplied:
            required_path(f"driver_factors.{key}", factors[key], base, errors)

    subsidence = project.get("subsidence_water", {})
    if subsidence.get("enabled") and subsidence.get("mode") == "estimate_volume":
        required_path("dem", inputs.get("dem"), base, errors)
        if not inputs.get("subsidence_depth_raster") and not inputs.get("subsidence_w_dat"):
            errors.append("subsidence volume requires subsidence_depth_raster or subsidence_w_dat")
        if inputs.get("subsidence_depth_raster"):
            required_path("subsidence_depth_raster", inputs.get("subsidence_depth_raster"), base, errors)
        if inputs.get("subsidence_w_dat"):
            required_path("subsidence_w_dat", inputs.get("subsidence_w_dat"), base, errors)
        level = subsidence.get("water_level_elevation_m") or inputs.get("water_surface_elevation_m")
        if not isinstance(level, (int, float)):
            errors.append("subsidence volume requires water_level_elevation_m")
        warnings.append("W data describes ground subsidence, not water depth; calculate water depth from DEM and water level.")

    ecosystem = project.get("ecosystem_service", {})
    if ecosystem.get("enabled"):
        if ecosystem.get("method") not in VALID_ECOSYSTEM_METHODS:
            errors.append(f"ecosystem_service.method must be one of {sorted(VALID_ECOSYSTEM_METHODS)}")
        required_path("ecosystem criteria_table", ecosystem.get("criteria_table"), base, errors)
        required_path("ecosystem config", ecosystem.get("config"), base, errors)

    gis_outputs = project.get("gis_outputs", {})
    if gis_outputs.get("enabled"):
        required_path("gis_outputs.aprx", gis_outputs.get("aprx"), base, errors)
        if not gis_outputs.get("layout_name"):
            errors.append("gis_outputs.layout_name is required when GIS outputs are enabled")
        if not gis_outputs.get("pdf") and not gis_outputs.get("png"):
            errors.append("configure gis_outputs.pdf and/or gis_outputs.png")

    return {"status": "valid" if not errors else "invalid", "project_id": project.get("project_id"),
            "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    args = parser.parse_args()
    result = validate(args.project.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
