#!/usr/bin/env python3
"""Create a fixed analysis grid or regrid a raster with an explicit data policy.

Categorical 10 m land-use maps are reduced to 30 m by rasterio's modal
resampling, so each 30 m output cell uses the majority class rather than an
interpolated class code.  Continuous factors use bilinear interpolation.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _resampling(kind: str, requested: str | None):
    from rasterio.enums import Resampling  # type: ignore
    name = (requested or {"categorical": "majority", "continuous": "bilinear", "circular": "nearest"}[kind]).lower()
    aliases = {"majority": "mode"}
    name = aliases.get(name, name)
    if name not in {"mode", "nearest", "bilinear", "cubic"}:
        raise ValueError(f"unsupported resampling method: {name}")
    return getattr(Resampling, name), name


def _target_from_cell_size(src, cell_size: float):
    from rasterio.transform import from_origin  # type: ignore
    if not src.crs or not src.crs.is_projected:
        raise ValueError("--cell-size-m requires a projected CRS")
    units = str(src.crs.linear_units or "").lower()
    if units not in {"metre", "meter", "metres", "meters", "m"}:
        raise ValueError("--cell-size-m requires projected metre coordinates")
    left, bottom, right, top = src.bounds
    width = max(1, math.ceil((right - left) / cell_size))
    height = max(1, math.ceil((top - bottom) / cell_size))
    return from_origin(left, top, cell_size, cell_size), width, height, src.crs


def regrid(input_path: Path, output: Path, *, master: Path | None, cell_size_m: float | None,
           kind: str, resampling: str | None) -> dict:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore
    from rasterio.warp import reproject  # type: ignore

    if (master is None) == (cell_size_m is None):
        raise ValueError("provide exactly one of --master or --cell-size-m")
    method, method_name = _resampling(kind, resampling)
    with rasterio.open(input_path) as source:
        if master:
            with rasterio.open(master) as reference:
                transform, width, height, crs = reference.transform, reference.width, reference.height, reference.crs
        else:
            transform, width, height, crs = _target_from_cell_size(source, float(cell_size_m))
        if not crs:
            raise ValueError("target grid has no CRS")
        nodata = source.nodata
        if kind == "categorical":
            if not all("int" in value or "uint" in value for value in source.dtypes):
                raise ValueError("categorical raster must use an integer pixel type")
            dtype = source.dtypes[0]
            if nodata is None:
                nodata = 0
        else:
            dtype, nodata = "float32", -9999.0
        profile = source.profile.copy()
        profile.update(driver="GTiff", width=width, height=height, transform=transform, crs=crs,
                       dtype=dtype, nodata=nodata, compress="deflate")
        output.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output, "w", **profile) as destination:
            for band in range(1, source.count + 1):
                target = np.full((height, width), nodata, dtype=dtype)
                reproject(source=rasterio.band(source, band), destination=target,
                          src_transform=source.transform, src_crs=source.crs, src_nodata=source.nodata,
                          dst_transform=transform, dst_crs=crs, dst_nodata=nodata, resampling=method)
                destination.write(target, band)
    report = {"status": "completed", "input": str(input_path.resolve()), "output": str(output.resolve()),
              "kind": kind, "resampling": method_name, "source_cell_size": None,
              "target_cell_size": [abs(transform.a), abs(transform.e)], "width": width, "height": height,
              "master": str(master.resolve()) if master else None}
    with rasterio.open(input_path) as source:
        report["source_cell_size"] = [abs(source.transform.a), abs(source.transform.e)]
    output.with_suffix(output.suffix + ".metadata.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path); parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--master", type=Path); parser.add_argument("--cell-size-m", type=float)
    parser.add_argument("--kind", choices=("categorical", "continuous", "circular"), required=True)
    parser.add_argument("--resampling")
    args = parser.parse_args()
    report = regrid(args.input.expanduser().resolve(), args.output.expanduser().resolve(),
                    master=args.master.expanduser().resolve() if args.master else None, cell_size_m=args.cell_size_m,
                    kind=args.kind, resampling=args.resampling)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
