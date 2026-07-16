#!/usr/bin/env python3
"""Rasterise standardised PIM points to the exact grid of a master raster.

The script is used when a project receives only w.dat/w.txt.  Coordinates are
interpreted in the CRS of the master LULC grid; it refuses points outside that
grid instead of silently assigning a CRS.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", required=True, type=Path); parser.add_argument("--master", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path); parser.add_argument("--metadata", type=Path)
    parser.add_argument("--fill-nearest", action="store_true",
                        help="Fill only cells inside --scope-vector and --max-distance-m")
    parser.add_argument("--scope-vector", type=Path,
                        help="Polygon limiting interpolation, normally a workface or predicted-subsidence boundary")
    parser.add_argument("--max-distance-m", type=float,
                        help="Maximum distance to a PIM sample for nearest-neighbour filling")
    args = parser.parse_args()
    try:
        import numpy as np  # type: ignore
        import rasterio  # type: ignore
    except ImportError as error:
        raise RuntimeError("w.dat rasterisation needs the validation dependencies (numpy and rasterio)") from error
    rows = list(csv.DictReader(args.points.open(encoding="utf-8-sig", newline="")))
    if not rows:
        raise ValueError("standardised w.dat contains no points")
    with rasterio.open(args.master) as master:
        if not master.crs or not master.crs.is_projected:
            raise ValueError("master LULC raster needs a projected CRS before w.dat rasterisation")
        sums = np.zeros((master.height, master.width), dtype="float64")
        count = np.zeros((master.height, master.width), dtype="uint32")
        outside = 0
        for number, row in enumerate(rows, start=2):
            try:
                x, y, depth = float(row["x"]), float(row["y"]), float(row["subsidence_depth_m"])
            except (KeyError, ValueError) as error:
                raise ValueError(f"invalid standardised w.dat row {number}") from error
            col, line = master.index(x, y)
            if not 0 <= col < master.height or not 0 <= line < master.width:
                outside += 1; continue
            sums[col, line] += depth; count[col, line] += 1
        if not count.any():
            raise ValueError("no w.dat points intersect the master LULC grid; check CRS and x/y columns")
        result = np.full((master.height, master.width), -9999.0, dtype="float32")
        result[count > 0] = (sums[count > 0] / count[count > 0]).astype("float32")
        scope_cells = 0
        filled_cells = 0
        if args.fill_nearest and (count == 0).any():
            if not args.scope_vector or args.max_distance_m is None or args.max_distance_m <= 0:
                raise ValueError("--fill-nearest requires --scope-vector and a positive --max-distance-m; unlimited interpolation is prohibited")
            units = str(master.crs.linear_units or "").lower()
            if units not in {"metre", "meter", "metres", "meters", "m"}:
                raise ValueError("bounded w.dat interpolation requires a projected metre master grid")
            from rasterio.features import rasterize  # type: ignore
            scope_path = args.scope_vector.expanduser().resolve()
            if scope_path.suffix.lower() in {".json", ".geojson"}:
                payload = json.loads(scope_path.read_text(encoding="utf-8-sig"))
                features = payload.get("features", []) if payload.get("type") == "FeatureCollection" else [payload]
                shapes = [feature.get("geometry", feature) for feature in features if isinstance(feature, dict)]
                shapes = [shape for shape in shapes if isinstance(shape, dict) and shape.get("type")]
                # GeoJSON may omit CRS under RFC 7946.  In that case the
                # caller's explicit master-grid contract remains the CRS
                # authority; non-GeoJSON vectors retain a strict check.
            else:
                import fiona  # type: ignore
                with fiona.open(scope_path) as source:
                    shapes = [feature["geometry"] for feature in source if feature.get("geometry")]
                    source_crs = source.crs_wkt or source.crs
                    if source_crs and str(source_crs) != str(master.crs):
                        raise ValueError("scope-vector CRS must match the master grid before interpolation")
            if not shapes:
                raise ValueError("scope vector contains no polygon geometries")
            scope = rasterize([(shape, 1) for shape in shapes], out_shape=(master.height, master.width),
                              transform=master.transform, fill=0, dtype="uint8").astype(bool)
            scope_cells = int(scope.sum())
            sample_rows, sample_cols = np.nonzero(count > 0)
            sample_values = result[sample_rows, sample_cols]
            missing_rows, missing_cols = np.nonzero(scope & (count == 0))
            # Chunked calculation keeps memory bounded for large mine grids.
            for begin in range(0, len(missing_rows), 50_000):
                end = min(begin + 50_000, len(missing_rows))
                dr = missing_rows[begin:end, None] - sample_rows[None, :]
                dc = missing_cols[begin:end, None] - sample_cols[None, :]
                squared = dr * dr + dc * dc
                nearest = np.argmin(squared, axis=1)
                # The grid was checked as projected metres.  For rotated grids
                # this is conservative; normal north-up analysis grids are exact.
                pixel_size = max(abs(master.transform.a), abs(master.transform.e))
                accepted = np.sqrt(squared[np.arange(len(nearest)), nearest]) * pixel_size <= args.max_distance_m
                result[missing_rows[begin:end][accepted], missing_cols[begin:end][accepted]] = sample_values[nearest[accepted]]
                filled_cells += int(accepted.sum())
        profile = master.profile.copy(); profile.update(dtype="float32", count=1, nodata=-9999.0, compress="deflate")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(args.output, "w", **profile) as destination:
            destination.write(result, 1)
        report = {"master": str(args.master.resolve()), "points": str(args.points.resolve()), "output": str(args.output.resolve()),
                  "crs": str(master.crs), "input_point_count": len(rows), "points_outside_grid": outside,
                  "cells_with_observed_depth": int((count > 0).sum()), "cells_filled_from_nearest_sample": filled_cells,
                  "cells_without_depth": int((result == -9999.0).sum()), "scope_cells": scope_cells,
                  "scope_vector": str(args.scope_vector.expanduser().resolve()) if args.scope_vector else None,
                  "max_interpolation_distance_m": args.max_distance_m, "nodata": -9999.0,
                  "interpolation": "nearest_PIM_sample_within_scope_and_distance" if args.fill_nearest else "mean_of_points_in_each_master_cell; no gap filling"}
    target = args.metadata or args.output.with_suffix(args.output.suffix + ".metadata.json")
    target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
