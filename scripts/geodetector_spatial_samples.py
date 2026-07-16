#!/usr/bin/env python3
"""Build aligned, finite GeoDetector samples from a target raster and factor rasters."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_factor(value: str) -> tuple[str, Path]:
    name, separator, raw = value.partition("=")
    if not separator or not name or not raw:
        raise ValueError("--factor uses NAME=path")
    return name, Path(raw).expanduser().resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path); parser.add_argument("--target-field", default="ecosystem_service_score")
    parser.add_argument("--factor", action="append", required=True); parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sample-step", type=int, default=1); parser.add_argument("--continuous-bins", type=int, default=6)
    args = parser.parse_args()
    if args.sample_step < 1 or args.continuous_bins < 2:
        raise SystemExit("sample-step must be positive and continuous-bins must be at least 2")
    import numpy as np  # type: ignore
    import rasterio  # type: ignore
    factors = [parse_factor(value) for value in args.factor]
    with rasterio.open(args.target.expanduser().resolve()) as target:
        target_data = target.read(1, masked=True)
        factor_data: dict[str, object] = {}
        for name, path in factors:
            with rasterio.open(path) as source:
                if source.crs != target.crs or source.width != target.width or source.height != target.height or source.transform != target.transform:
                    raise ValueError(f"factor grid differs from target: {name}")
                factor_data[name] = source.read(1, masked=True)
        rows: list[dict[str, object]] = []
        for row in range(0, target.height, args.sample_step):
            for col in range(0, target.width, args.sample_step):
                if target_data.mask[row, col]:
                    continue
                values = {name: data[row, col] for name, data in factor_data.items()}
                if any(np.ma.is_masked(value) or not np.isfinite(float(value)) for value in values.values()):
                    continue
                x, y = target.transform * (col + 0.5, row + 0.5)
                rows.append({"sample_id": f"r{row}_c{col}", "x": float(x), "y": float(y),
                             args.target_field: float(target_data[row, col]), **{name: float(value) for name, value in values.items()}})
    if len(rows) < 2:
        raise ValueError("fewer than two co-located finite samples remain after NoData filtering")
    # GeoDetector operates on strata.  Values with many distinct levels are
    # quantile-classified reproducibly; existing integer thematic factors stay
    # intact as classes.
    for name, _ in factors:
        values = np.array([float(row[name]) for row in rows])
        if len(np.unique(values)) > args.continuous_bins:
            edges = np.unique(np.quantile(values, np.linspace(0, 1, args.continuous_bins + 1)))
            for row in rows:
                row[name] = f"Q{min(len(edges) - 1, int(np.searchsorted(edges, float(row[name]), side='right')))}"
        else:
            for row in rows:
                row[name] = str(row[name])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["sample_id", "x", "y", args.target_field, *[name for name, _ in factors]]
    with args.output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    report = {"status": "completed", "output": str(args.output.resolve()), "sample_count": len(rows),
              "target": str(args.target.expanduser().resolve()), "factors": {name: str(path) for name, path in factors},
              "sample_step": args.sample_step, "continuous_bins": args.continuous_bins,
              "nodata_policy": "discard_samples_with_NoData_in_target_or_any_factor"}
    args.output.with_suffix(args.output.suffix + ".metadata.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
