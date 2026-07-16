#!/usr/bin/env python3
"""Validate local raster grids, codes and carbon-table coverage before analysis."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _rasterio_info(path: Path) -> dict[str, Any]:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore

    with rasterio.open(path) as src:
        values: set[int] = set()
        minimum: float | None = None
        maximum: float | None = None
        nonfinite_count = 0
        integer = all("int" in dtype or "uint" in dtype for dtype in src.dtypes)
        for _, window in src.block_windows(1):
            data = src.read(1, window=window, masked=True)
            raw = data.compressed()
            finite = raw[np.isfinite(raw)]
            nonfinite_count += int(raw.size - finite.size)
            if finite.size:
                minimum = float(finite.min()) if minimum is None else min(minimum, float(finite.min()))
                maximum = float(finite.max()) if maximum is None else max(maximum, float(finite.max()))
                if len(values) <= 4096:
                    values.update(int(item) for item in np.unique(finite)[:4097])
        return {
            "path": str(path.resolve()), "inspector": "rasterio", "crs": str(src.crs) if src.crs else None,
            "width": src.width, "height": src.height, "band_count": src.count, "transform": list(src.transform)[:6],
            "nodata": src.nodata, "dtypes": list(src.dtypes), "integer": integer,
            "minimum": minimum, "maximum": maximum, "nonfinite_count": nonfinite_count,
            "is_projected": bool(src.crs and src.crs.is_projected),
            "linear_units": src.crs.linear_units if src.crs and src.crs.is_projected else None,
            "values": sorted(values) if len(values) <= 4096 else None,
            "band_descriptions": [item or "" for item in src.descriptions],
            "tags": {str(key).lower(): str(value) for key, value in src.tags().items()},
        }


def _gdal_info(path: Path) -> dict[str, Any]:
    executable = os.getenv("MINING_GDALINFO") or shutil.which("gdalinfo")
    if not executable:
        raise RuntimeError("no raster inspector is available; install rasterio or provide GDALINFO/MINING_GDALINFO")
    process = subprocess.run([executable, "-json", "-stats", str(path)], text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, encoding="utf-8", errors="replace", check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or f"gdalinfo returned {process.returncode}")
    raw = json.loads(process.stdout)
    band = (raw.get("bands") or [{}])[0]
    data_type = str(band.get("type", "")).lower()
    return {
        "path": str(path.resolve()), "inspector": "gdalinfo", "crs": raw.get("coordinateSystem", {}).get("wkt"),
        "width": (raw.get("size") or [None, None])[0], "height": (raw.get("size") or [None, None])[1],
        "band_count": len(raw.get("bands") or []),
        "transform": raw.get("geoTransform"), "nodata": band.get("noDataValue"), "dtypes": [data_type],
        "integer": any(token in data_type for token in ("int", "byte")),
        "minimum": band.get("minimum"), "maximum": band.get("maximum"), "nonfinite_count": None,
        "is_projected": bool(raw.get("coordinateSystem", {}).get("wkt")), "linear_units": None, "values": None,
        "band_descriptions": [], "tags": raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {},
    }


def inspect_raster(path: Path) -> dict[str, Any]:
    try:
        return _rasterio_info(path)
    except ModuleNotFoundError:
        return _gdal_info(path)


def _finite_coordinates(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, list):
        return bool(value) and all(_finite_coordinates(item) for item in value)
    return False


def inspect_vector(path: Path) -> dict[str, Any]:
    """Inspect GeoJSON directly; use Fiona or ogrinfo for other local vector formats."""
    if path.suffix.lower() in {".json", ".geojson"}:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        features = payload.get("features", []) if payload.get("type") == "FeatureCollection" else [payload]
        geometries = [item.get("geometry", item) for item in features if isinstance(item, dict)]
        types = sorted({str(item.get("type")) for item in geometries if isinstance(item, dict) and item.get("type")})
        invalid = sum(1 for item in geometries if not isinstance(item, dict) or not _finite_coordinates(item.get("coordinates")))
        crs = payload.get("crs", {})
        name = crs.get("properties", {}).get("name") if isinstance(crs, dict) else None
        return {"path": str(path.resolve()), "inspector": "geojson", "crs": name, "feature_count": len(features),
                "geometry_types": types, "invalid_geometry_count": invalid}
    try:
        import fiona  # type: ignore
        with fiona.open(path) as source:
            types = sorted({str(item.get("geometry", {}).get("type")) for item in source if item.get("geometry")})
            return {"path": str(path.resolve()), "inspector": "fiona", "crs": str(source.crs_wkt or source.crs) or None,
                    "feature_count": len(source), "geometry_types": types, "invalid_geometry_count": None}
    except ModuleNotFoundError:
        executable = os.getenv("MINING_OGRINFO") or shutil.which("ogrinfo")
        if not executable:
            raise RuntimeError("no vector inspector is available; install Fiona or provide MINING_OGRINFO")
        process = subprocess.run([executable, "-ro", "-so", "-al", "-json", str(path)], text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, encoding="utf-8", errors="replace", check=False)
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or f"ogrinfo returned {process.returncode}")
        payload = json.loads(process.stdout)
        features = payload.get("features", [])
        return {"path": str(path.resolve()), "inspector": "ogrinfo", "crs": None, "feature_count": len(features),
                "geometry_types": sorted({str(item.get("geometry", {}).get("type")) for item in features if item.get("geometry")}),
                "invalid_geometry_count": None}


def _same_grid(master: dict[str, Any], item: dict[str, Any]) -> bool:
    if master.get("width") != item.get("width") or master.get("height") != item.get("height"):
        return False
    try:
        from rasterio.crs import CRS  # type: ignore
        if not CRS.from_user_input(master.get("crs")).equals(CRS.from_user_input(item.get("crs"))):
            return False
    except Exception:
        if (master.get("crs") or "") != (item.get("crs") or ""):
            return False
    left, right = master.get("transform"), item.get("transform")
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
        return False
    cell = max(abs(float(left[0])), abs(float(left[4])), abs(float(right[0])), abs(float(right[4])), 1.0)
    tolerance = max(1e-9, cell * 1e-8)
    return all(math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=tolerance) for a, b in zip(left, right))


def _carbon_codes(path: Path) -> set[int]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or "lucode" not in rows[0]:
        raise ValueError("carbon density table must contain lucode")
    codes: list[int] = []
    for row in rows:
        code = int(float(row.get("lucode", "")))
        codes.append(code)
        for field, value in row.items():
            if field.startswith("c_") and (not value or not math.isfinite(float(value)) or float(value) < 0):
                raise ValueError(f"carbon density {field} for lucode {code} must be a finite non-negative number")
    duplicates = sorted({item for item in codes if codes.count(item) > 1})
    if duplicates:
        raise ValueError(f"carbon density table has duplicate lucode values: {duplicates}")
    return set(codes)


def validate(spec: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    checks: list[str] = []
    datasets = spec.get("datasets", [])
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("spatial preflight requires at least one dataset")
    inspected: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for entry in datasets:
        name, raw = str(entry.get("name", "dataset")), entry.get("path")
        path = Path(str(raw)).expanduser().resolve()
        if not path.exists():
            errors.append(f"{name}: file does not exist: {path}")
            continue
        try:
            if entry.get("kind") == "vector":
                info = inspect_vector(path)
                inspected[name] = info
                if entry.get("require_crs") and not info.get("crs"):
                    errors.append(f"{name}: vector CRS is missing")
                if not info.get("feature_count"):
                    errors.append(f"{name}: vector contains no features")
                if info.get("invalid_geometry_count"):
                    errors.append(f"{name}: vector has invalid or non-finite geometries")
                expected_types = set(entry.get("geometry_types", []))
                if expected_types and not set(info.get("geometry_types", [])) <= expected_types:
                    errors.append(f"{name}: vector geometry type is outside {sorted(expected_types)}")
                checks.append(name)
                continue
            info = inspect_raster(path)
            inspected[name] = info
            if not info.get("crs"):
                errors.append(f"{name}: CRS is missing")
            if not info.get("width") or not info.get("height"):
                errors.append(f"{name}: raster dimensions are invalid")
            if entry.get("require_projected_meters") and (not info.get("is_projected") or str(info.get("linear_units", "")).lower() not in {"metre", "meter", "metres", "meters", "m"}):
                errors.append(f"{name}: projected metre CRS is required for area or volume calculations")
            if entry.get("require_nodata") and info.get("nodata") is None:
                errors.append(f"{name}: an explicit NoData value is required")
            expected_cell = entry.get("expected_cell_size_m")
            if expected_cell is not None:
                transform = info.get("transform") or []
                if (not isinstance(expected_cell, (int, float)) or float(expected_cell) <= 0 or len(transform) < 6 or
                        not math.isclose(abs(float(transform[0])), float(expected_cell), rel_tol=1e-8, abs_tol=1e-8) or
                        not math.isclose(abs(float(transform[4])), float(expected_cell), rel_tol=1e-8, abs_tol=1e-8)):
                    errors.append(f"{name}: cell size is not the required {expected_cell:g} m analysis grid")
            if entry.get("kind") == "continuous" and info.get("nonfinite_count"):
                errors.append(f"{name}: continuous raster contains {info['nonfinite_count']} NaN or infinite values")
            if entry.get("kind") == "lulc":
                if not info.get("integer"):
                    errors.append(f"{name}: LULC must use an integer pixel type")
                allowed = set(entry.get("allowed_codes", []))
                values = info.get("values")
                if allowed and values is not None:
                    unknown = sorted(set(values) - allowed)
                    if unknown:
                        errors.append(f"{name}: unrecognised LULC codes: {unknown}")
                if info.get("nodata") in allowed:
                    errors.append(f"{name}: NoData value conflicts with an allowed LULC code")
            minimum_bands = entry.get("minimum_band_count")
            if minimum_bands is not None and (not isinstance(minimum_bands, int) or int(info.get("band_count") or 0) < minimum_bands):
                errors.append(f"{name}: raster band count is below required minimum {minimum_bands}")
            expected_bands = entry.get("expected_band_count")
            if expected_bands is not None and (not isinstance(expected_bands, int) or int(info.get("band_count") or 0) != expected_bands):
                errors.append(f"{name}: raster band count differs from model contract {expected_bands}")
            expected_names = entry.get("expected_band_names")
            descriptions = [value.lower() for value in info.get("band_descriptions", []) if value]
            if expected_names and descriptions and [str(value).lower() for value in expected_names] != descriptions:
                errors.append(f"{name}: raster band descriptions differ from the model contract")
            expected_range = entry.get("expected_value_range")
            if expected_range is not None:
                if (not isinstance(expected_range, list) or len(expected_range) != 2 or
                        not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in expected_range) or
                        float(expected_range[0]) >= float(expected_range[1])):
                    errors.append(f"{name}: expected_value_range must be [minimum, maximum]")
                elif info.get("minimum") is not None and (float(info["minimum"]) < float(expected_range[0]) or float(info["maximum"]) > float(expected_range[1])):
                    errors.append(f"{name}: raster values fall outside the model value range")
            expected_sensor = entry.get("sensor")
            actual_sensor = (info.get("tags") or {}).get("sensor") or (info.get("tags") or {}).get("platform")
            if expected_sensor and actual_sensor and str(expected_sensor).lower() != str(actual_sensor).lower():
                errors.append(f"{name}: raster sensor tag differs from model contract {expected_sensor}")
            elif expected_sensor and not actual_sensor:
                warnings.append(f"{name}: model expects sensor {expected_sensor}, but the raster carries no sensor tag")
            if entry.get("kind") == "subsidence_depth":
                minimum = info.get("minimum")
                if minimum is None:
                    errors.append(f"{name}: subsidence-depth minimum could not be inspected")
                elif float(minimum) < -1e-9:
                    errors.append(f"{name}: subsidence depth contains negative values under positive_down")
            checks.append(name)
        except Exception as error:
            errors.append(f"{name}: {error}")
    master_name = spec.get("master")
    if master_name and master_name in inspected:
        master = inspected[master_name]
        for entry in datasets:
            name = str(entry.get("name", "dataset"))
            if entry.get("must_align") and name in inspected and not _same_grid(master, inspected[name]):
                errors.append(f"{name}: grid differs from master {master_name}")
    elif master_name:
        errors.append(f"master dataset was not inspected: {master_name}")
    carbon_path = spec.get("carbon_density")
    lulc_names = [str(item.get("name")) for item in datasets if item.get("kind") == "lulc"]
    if carbon_path and lulc_names:
        try:
            carbon_codes = _carbon_codes(Path(str(carbon_path)).expanduser().resolve())
            for name in lulc_names:
                values = inspected.get(name, {}).get("values")
                if values is not None:
                    missing = sorted(set(values) - carbon_codes)
                    if missing:
                        errors.append(f"{name}: carbon density has no lucode for {missing}")
            checks.append("carbon-density coverage")
        except Exception as error:
            errors.append(f"carbon density: {error}")
    datum = spec.get("vertical_datum", {})
    if datum:
        dem, water = datum.get("dem"), datum.get("water_level")
        if not dem or not water:
            errors.append("DEM and water-level vertical datum must both be declared for volume calculation")
        elif str(dem).strip().lower() != str(water).strip().lower():
            errors.append("DEM and water level use different vertical datums")
        else:
            checks.append("vertical datum")
    return {"status": "failed" if errors else "completed", "checks": checks, "warnings": warnings, "errors": errors,
            "datasets": inspected, "master": master_name}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8-sig"))
    report = validate(spec)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
