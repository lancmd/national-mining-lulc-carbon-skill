#!/usr/bin/env python3
"""Build scenario-service tables at scenario-total or regular-grid scale."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


def raster_total(path: Path, aggregation: str = "sum") -> float:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore
    with rasterio.open(path) as src:
        total, count = 0.0, 0
        cell_area_m2 = abs(float(src.transform.a * src.transform.e))
        for _, window in src.block_windows(1):
            values = src.read(1, window=window, masked=True)
            valid = values.compressed()
            total += float(valid.sum(dtype="float64")); count += int(valid.size)
    if not count:
        raise ValueError(f"service raster has no valid pixels (NoData is not a zero service): {path}")
    if aggregation == "depth_mm_to_m3":
        return total * cell_area_m2 / 1000.0
    if aggregation == "mean":
        return total / count if count else 0.0
    return total


def grid_totals(path: Path, cell_pixels: int, aggregation: str = "sum") -> dict[str, float | None]:
    """Aggregate a raster into deterministic regular-grid units without vector dependencies."""
    if cell_pixels < 1:
        raise ValueError("grid_cell_pixels must be a positive integer")
    import numpy as np  # type: ignore
    import rasterio  # type: ignore
    from rasterio.windows import Window  # type: ignore
    result: dict[str, float | None] = {}
    with rasterio.open(path) as src:
        for row in range(0, src.height, cell_pixels):
            for col in range(0, src.width, cell_pixels):
                height, width = min(cell_pixels, src.height - row), min(cell_pixels, src.width - col)
                values = src.read(1, window=Window(col, row, width, height), masked=True)
                valid = values.compressed()
                if not valid.size:
                    result[f"r{row // cell_pixels:05d}_c{col // cell_pixels:05d}"] = None
                    continue
                total = float(valid.sum(dtype="float64"))
                if aggregation == "depth_mm_to_m3":
                    total *= abs(float(src.transform.a * src.transform.e)) / 1000.0
                elif aggregation == "mean":
                    total = total / int(valid.size)
                result[f"r{row // cell_pixels:05d}_c{col // cell_pixels:05d}"] = total
    return result


def raster_signature(path: Path) -> dict[str, Any]:
    import rasterio  # type: ignore
    with rasterio.open(path) as src:
        return {"crs": src.crs.to_string() if src.crs else None, "width": src.width, "height": src.height,
                "transform": [float(value) for value in list(src.transform)[:6]]}


def grids_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (left["crs"] == right["crs"] and left["width"] == right["width"] and left["height"] == right["height"] and
            all(math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-9) for a, b in zip(left["transform"], right["transform"])))


def grid_geojson(path: Path, cell_pixels: int, output: Path) -> str:
    """Write one geometry per regular-grid unit in the service raster CRS."""
    import rasterio  # type: ignore
    from rasterio.windows import Window  # type: ignore
    features = []
    with rasterio.open(path) as src:
        for row in range(0, src.height, cell_pixels):
            for col in range(0, src.width, cell_pixels):
                window = Window(col, row, min(cell_pixels, src.width - col), min(cell_pixels, src.height - row))
                bounds = rasterio.windows.bounds(window, src.transform)
                xmin, ymin, xmax, ymax = [float(value) for value in bounds]
                unit_id = f"r{row // cell_pixels:05d}_c{col // cell_pixels:05d}"
                features.append({"type": "Feature", "properties": {"unit_id": unit_id}, "geometry": {"type": "Polygon",
                    "coordinates": [[[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]]]}})
        payload: dict[str, Any] = {"type": "FeatureCollection", "features": features}
        if src.crs:
            payload["crs"] = {"type": "name", "properties": {"name": src.crs.to_string()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(output.resolve())


def read_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def build(service_rasters: dict[str, dict[str, Path]], supplemental: Path | None, output: Path,
          scenario_field: str = "scenario", id_field: str = "unit_id", grid_cell_pixels: int | None = None,
          service_units: dict[str, str] | None = None, grid_geometry: Path | None = None,
          service_aggregations: dict[str, str] | None = None) -> dict[str, Any]:
    if not service_rasters:
        raise ValueError("at least one scenario service raster is required")
    supplied = read_rows(supplemental)
    supplied_by_key = {(str(row.get(scenario_field, "")).strip().upper(), str(row.get(id_field, "")).strip()): dict(row)
                       for row in supplied}
    result: list[dict[str, Any]] = []
    scale = "regular_grid" if grid_cell_pixels else "scenario_total"
    reference: dict[str, Any] | None = None
    reference_path: Path | None = None
    for scenario, services in sorted(service_rasters.items()):
        code = scenario.strip().upper()
        if not services:
            continue
        for field, raster in services.items():
            if not raster.exists():
                raise FileNotFoundError(f"InVEST service raster is missing for {code}/{field}: {raster}")
            signature = raster_signature(raster)
            if reference is None:
                reference, reference_path = signature, raster
            elif not grids_match(reference, signature):
                raise ValueError(f"InVEST service raster grid differs from reference: {raster}")
        if grid_cell_pixels:
            by_field = {field: grid_totals(raster, grid_cell_pixels, (service_aggregations or {}).get(field, "sum")) for field, raster in services.items()}
            unit_ids = set().union(*[set(values) for values in by_field.values()])
            for unit_id in sorted(unit_ids):
                if any(values.get(unit_id) is None for values in by_field.values()):
                    # Preserve NoData semantics: an analysis unit with missing
                    # coverage is excluded, never silently converted to zero.
                    continue
                row: dict[str, Any] = supplied_by_key.get((code, unit_id), {scenario_field: code, id_field: unit_id})
                row.setdefault(scenario_field, code); row.setdefault(id_field, unit_id)
                for field, values in by_field.items():
                    row[field] = values[unit_id]
                result.append(row)
        else:
            row = supplied_by_key.get((code, code), {scenario_field: code, id_field: code})
            row.setdefault(scenario_field, code); row.setdefault(id_field, code)
            for field, raster in services.items():
                row[field] = raster_total(raster, (service_aggregations or {}).get(field, "sum"))
            result.append(row)
    fields = sorted({key for row in result for key in row})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(result)
    geometry = grid_geojson(reference_path, grid_cell_pixels, grid_geometry) if grid_cell_pixels and grid_geometry and reference_path else None
    report = {"status": "completed", "spatial_scale": scale, "aggregation": "sum_of_valid_pixel_values",
              "grid_cell_pixels": grid_cell_pixels,
              "record_count": len(result), "scenarios": sorted(service_rasters), "output": str(output.resolve()),
              "grid_geometry": geometry, "reference_grid": reference,
              "service_units": {field: (service_units or {}).get(field, "undeclared")
                                for services in service_rasters.values() for field in services},
              "service_aggregations": {field: (service_aggregations or {}).get(field, "sum")
                                       for services in service_rasters.values() for field in services},
              "service_rasters": {scenario: {field: str(path.resolve()) for field, path in values.items()}
                                  for scenario, values in service_rasters.items()}}
    output.with_suffix(output.suffix + ".metadata.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-raster", action="append", default=[],
                        help="SCENARIO=FIELD=path; repeat for every scenario/service output")
    parser.add_argument("--carbon-raster", action="append", default=[],
                        help="Backward-compatible SCENARIO=path alias for carbon_storage_t_c")
    parser.add_argument("--supplemental", type=Path)
    parser.add_argument("--scenario-field", default="scenario")
    parser.add_argument("--id-field", default="unit_id")
    parser.add_argument("--grid-cell-pixels", type=int)
    parser.add_argument("--grid-geometry", type=Path, help="GeoJSON regular-grid geometry when aggregating rasters")
    parser.add_argument("--service-unit", action="append", default=[], help="FIELD=unit; repeat for each service raster")
    parser.add_argument("--service-aggregation", action="append", default=[], help="FIELD=sum|mean|depth_mm_to_m3")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rasters: dict[str, dict[str, Path]] = {}
    for item in args.service_raster:
        scenario, separator, rest = item.partition("=")
        field, separator2, raw = rest.partition("=")
        if not separator or not separator2 or not scenario or not field or not raw:
            raise SystemExit("--service-raster uses SCENARIO=FIELD=path")
        rasters.setdefault(scenario.upper(), {})[field] = Path(raw).expanduser().resolve()
    for item in args.carbon_raster:
        scenario, separator, raw = item.partition("=")
        if not separator or not scenario or not raw:
            raise SystemExit("--carbon-raster uses SCENARIO=path")
        rasters.setdefault(scenario.upper(), {})["carbon_storage_t_c"] = Path(raw).expanduser().resolve()
    units: dict[str, str] = {}
    for item in args.service_unit:
        field, separator, unit = item.partition("=")
        if not separator or not field or not unit:
            raise SystemExit("--service-unit uses FIELD=unit")
        units[field] = unit
    aggregations: dict[str, str] = {}
    for item in args.service_aggregation:
        field, separator, method = item.partition("=")
        if not separator or not field or method not in {"sum", "mean", "depth_mm_to_m3"}:
            raise SystemExit("--service-aggregation uses FIELD=sum|mean|depth_mm_to_m3")
        aggregations[field] = method
    report = build(rasters, args.supplemental, args.output, args.scenario_field, args.id_field, args.grid_cell_pixels,
                   units, args.grid_geometry.resolve() if args.grid_geometry else None, aggregations)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
