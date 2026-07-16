#!/usr/bin/env python3
"""Create mode-specific evidence for a classify-only subsidence-water result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lulc", required=True, type=Path); parser.add_argument("--water-code", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path); args = parser.parse_args()
    try:
        import numpy as np  # type: ignore
        import rasterio  # type: ignore
    except ImportError as error:
        raise RuntimeError("subsidence-water evidence requires numpy and rasterio") from error
    with rasterio.open(args.lulc) as source:
        values = source.read(1, masked=True)
        count = int(np.sum(values.compressed() == args.water_code))
        area = abs(source.transform.a * source.transform.e)
        report = {"status": "completed", "mode": "classify_only", "lulc": str(args.lulc.resolve()),
                  "water_code": args.water_code, "water_cell_count": count, "water_area_m2": count * area,
                  "crs": str(source.crs) if source.crs else None, "cell_area_m2": area}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
