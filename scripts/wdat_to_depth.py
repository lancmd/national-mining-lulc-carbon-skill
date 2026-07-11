#!/usr/bin/env python3
"""Standardise external PIM w.dat/w.txt points into positive subsidence-depth CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_rows(path: Path, delimiter: str | None) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//", ";")):
            continue
        rows.append(line.split(delimiter) if delimiter else line.replace(",", " ").split())
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--x-column", default="0")
    parser.add_argument("--y-column", default="1")
    parser.add_argument("--w-column", default="2")
    parser.add_argument("--unit", choices=("m", "mm"), default="m")
    parser.add_argument("--sign", choices=("negative_down", "positive_down"), default="negative_down")
    parser.add_argument("--delimiter", default=None)
    args = parser.parse_args()
    x_col, y_col, w_col = int(args.x_column), int(args.y_column), int(args.w_column)
    rows = parse_rows(args.input.resolve(), args.delimiter)
    if not rows:
        raise ValueError("no data rows found")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["x", "y", "w_raw", "subsidence_depth_m"])
        writer.writeheader()
        for number, row in enumerate(rows, start=1):
            try:
                x, y, w = float(row[x_col]), float(row[y_col]), float(row[w_col])
            except (IndexError, ValueError) as error:
                raise ValueError(f"invalid data at row {number}") from error
            depth = w / 1000.0 if args.unit == "mm" else w
            if args.sign == "negative_down":
                depth = -depth
            if depth < 0:
                raise ValueError(f"depth is negative after sign conversion at row {number}")
            writer.writerow({"x": x, "y": y, "w_raw": w, "subsidence_depth_m": depth})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
