#!/usr/bin/env python3
"""Validate local non-Carbon InVEST datastacks before scenario execution."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


REQUIRED: dict[str, tuple[str, ...]] = {
    "annual_water_yield": ("lulc_path", "precipitation_path", "eto_path", "depth_to_root_rest_layer_path", "pawc_path",
                            "watersheds_path", "biophysical_table_path", "seasonality_constant"),
    "habitat_quality": ("lulc_cur_path", "threats_table_path", "sensitivity_table_path", "half_saturation_constant"),
    "sediment_delivery_ratio": ("lulc_path", "dem_path", "erosivity_path", "erodibility_path", "watersheds_path", "biophysical_table_path"),
    "nutrient_delivery_ratio": ("lulc_path", "dem_path", "runoff_proxy_path", "watersheds_path", "biophysical_table_path"),
}


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve(value: Any, base: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def headers(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return set(csv.DictReader(stream).fieldnames or [])


def missing_headers(actual: set[str], required: set[str]) -> set[str]:
    """Compare InVEST table headers case-insensitively without rewriting them."""
    present = {value.casefold() for value in actual}
    return {value for value in required if value.casefold() not in present}


def validate(model: str, datastack: Path) -> dict[str, Any]:
    payload = read(datastack); args = payload.get("args", {})
    if not isinstance(args, dict):
        raise ValueError("datastack args must be an object")
    errors: list[str] = []; warnings: list[str] = []
    for name in REQUIRED[model]:
        value = args.get(name)
        if value in (None, ""):
            errors.append(f"missing InVEST argument: {name}")
        elif name.endswith("_path"):
            path = resolve(value, datastack.parent)
            if path is None or not path.exists():
                errors.append(f"input does not exist: {name} = {path}")
    numeric = "seasonality_constant" if model == "annual_water_yield" else "half_saturation_constant" if model == "habitat_quality" else None
    if numeric and args.get(numeric) not in (None, "") and (not isinstance(args[numeric], (int, float)) or float(args[numeric]) <= 0):
        errors.append(f"{numeric} must be a positive number")
    try:
        if model == "annual_water_yield" and args.get("biophysical_table_path"):
            table = resolve(args["biophysical_table_path"], datastack.parent)
            missing = missing_headers(headers(table), {"lucode", "root_depth", "kc", "lulc_veg"}) if table else {"table"}
            if missing: errors.append("Annual Water Yield biophysical table misses: " + ", ".join(sorted(missing)))
        if model == "habitat_quality":
            threats = resolve(args.get("threats_table_path"), datastack.parent)
            sensitivity = resolve(args.get("sensitivity_table_path"), datastack.parent)
            threat_headers = headers(threats) if threats else set(); sensitivity_headers = headers(sensitivity) if sensitivity else set()
            missing_threat = {"threat", "max_dist", "weight", "decay", "cur_path"} - threat_headers
            if missing_threat: errors.append("Habitat Quality threats table misses: " + ", ".join(sorted(missing_threat)))
            # InVEST Habitat Quality uses the field name ``lulc`` rather than
            # Carbon's ``lucode``.  Treating them as interchangeable lets an
            # invalid table pass preflight and fail only after a costly run.
            missing_sensitivity = missing_headers(sensitivity_headers, {"lulc", "habitat"})
            if missing_sensitivity: errors.append("Habitat Quality sensitivity table misses: " + ", ".join(sorted(missing_sensitivity)))
            if threats and threat_headers and sensitivity_headers:
                with threats.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                names = {str(row.get("threat", "")).strip() for row in rows}
                absent = sorted(name for name in names if name and name not in sensitivity_headers)
                if absent: errors.append("Habitat Quality sensitivity table has no columns for threats: " + ", ".join(absent))
                for row in rows:
                    name, raw_path = str(row.get("threat", "")).strip(), row.get("cur_path")
                    raster = resolve(raw_path, threats.parent)
                    if not raster or not raster.exists():
                        errors.append(f"Habitat Quality threat raster does not exist for {name or 'unnamed'}: {raster}")
            if not args.get("access_vector_path"):
                warnings.append("access_vector_path is absent; habitat access is treated as unrestricted")
        if model in {"sediment_delivery_ratio", "nutrient_delivery_ratio"} and args.get("biophysical_table_path"):
            table = resolve(args["biophysical_table_path"], datastack.parent)
            missing = missing_headers(headers(table), {"lucode"}) if table else {"table"}
            if missing:
                errors.append(f"{model} biophysical table misses: " + ", ".join(sorted(missing)))
    except (OSError, csv.Error) as error:
        errors.append(f"cannot read InVEST parameter table: {error}")
    return {"status": "completed" if not errors else "failed", "model": model, "datastack": str(datastack.resolve()),
            "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(REQUIRED)); parser.add_argument("--datastack", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path); args = parser.parse_args()
    result = validate(args.model, args.datastack.resolve()); args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
