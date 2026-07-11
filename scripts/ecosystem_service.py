#!/usr/bin/env python3
"""Compute Min-Max or AHP-weighted ecosystem-service scores from a local CSV."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def normalise_weights(values: list[float]) -> list[float]:
    total = sum(values)
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    return [value / total for value in values]


def ahp_weights(matrix: list[list[float]]) -> tuple[list[float], float, float]:
    size = len(matrix)
    if size < 1 or any(len(row) != size for row in matrix):
        raise ValueError("AHP matrix must be square")
    for row in matrix:
        if any(not isinstance(value, (int, float)) or value <= 0 for value in row):
            raise ValueError("AHP matrix values must be positive")
    for i in range(size):
        if not math.isclose(matrix[i][i], 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("AHP diagonal values must be 1")
        for j in range(i + 1, size):
            if not math.isclose(matrix[i][j] * matrix[j][i], 1.0, rel_tol=1e-4, abs_tol=1e-4):
                raise ValueError("AHP matrix must be reciprocal")
    vector = [1.0 / size] * size
    for _ in range(1000):
        product = [sum(matrix[i][j] * vector[j] for j in range(size)) for i in range(size)]
        updated = normalise_weights(product)
        if max(abs(updated[i] - vector[i]) for i in range(size)) < 1e-12:
            vector = updated
            break
        vector = updated
    products = [sum(matrix[i][j] * vector[j] for j in range(size)) for i in range(size)]
    lambda_max = sum(products[i] / vector[i] for i in range(size)) / size
    ci = 0.0 if size <= 2 else (lambda_max - size) / (size - 1)
    ri = RANDOM_INDEX.get(size)
    if ri is None:
        raise ValueError("AHP supports at most 10 criteria")
    cr = 0.0 if ri == 0 else ci / ri
    return vector, lambda_max, cr


def evaluate(criteria_table: Path, config_path: Path, output_path: Path) -> dict[str, Any]:
    config = load_json(config_path)
    if config.get("schema_version") != 1:
        raise ValueError("ecosystem config schema_version must be 1")
    method = config.get("method")
    if method not in {"minmax", "ahp"}:
        raise ValueError("method must be minmax or ahp")
    criteria = config.get("criteria", [])
    if not criteria:
        raise ValueError("criteria are required")
    with criteria_table.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
        fieldnames = stream.seek(0) or []
    if not rows:
        raise ValueError("criteria table has no rows")
    id_field = config.get("id_field", "unit_id")
    required = [id_field] + [item.get("field") for item in criteria]
    missing = [field for field in required if not field or field not in rows[0]]
    if missing:
        raise ValueError(f"criteria table misses columns: {', '.join(missing)}")
    values: dict[str, list[float]] = {}
    for item in criteria:
        field = item["field"]
        try:
            values[field] = [float(row[field]) for row in rows]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"criterion {field} must contain finite numeric values") from error
        if any(not math.isfinite(value) for value in values[field]):
            raise ValueError(f"criterion {field} contains non-finite values")
    if method == "minmax":
        weights = normalise_weights([float(item.get("weight", 0)) for item in criteria])
        lambda_max = consistency_ratio = None
    else:
        matrix = config.get("ahp", {}).get("pairwise_matrix")
        if not isinstance(matrix, list) or len(matrix) != len(criteria):
            raise ValueError("AHP pairwise_matrix must match criteria length")
        weights, lambda_max, consistency_ratio = ahp_weights(matrix)
        threshold = float(config.get("ahp", {}).get("consistency_threshold", 0.1))
        if consistency_ratio > threshold:
            raise ValueError(f"AHP consistency ratio {consistency_ratio:.4f} exceeds threshold {threshold:.4f}")
    output_rows: list[dict[str, Any]] = []
    normalised: dict[str, list[float]] = {}
    for item in criteria:
        field = item["field"]
        lower, upper = min(values[field]), max(values[field])
        if math.isclose(lower, upper):
            scores = [0.5] * len(rows)
        elif item.get("direction", "benefit") == "benefit":
            scores = [(value - lower) / (upper - lower) for value in values[field]]
        elif item.get("direction") == "cost":
            scores = [(upper - value) / (upper - lower) for value in values[field]]
        else:
            raise ValueError(f"criterion direction must be benefit or cost: {field}")
        normalised[field] = scores
    for index, row in enumerate(rows):
        result = {id_field: row[id_field]}
        total = 0.0
        for criterion, weight in zip(criteria, weights):
            field = criterion["field"]
            result[f"norm_{field}"] = normalised[field][index]
            total += weight * normalised[field][index]
        result["ecosystem_service_score"] = total
        output_rows.append(result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output_rows[0]))
        writer.writeheader(); writer.writerows(output_rows)
    metadata = {"method": method, "criteria": [item["field"] for item in criteria], "weights": weights,
                "lambda_max": lambda_max, "consistency_ratio": consistency_ratio, "output": str(output_path.resolve())}
    output_path.with_suffix(output_path.suffix + ".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--criteria-table", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.criteria_table.resolve(), args.config.resolve(), args.output.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
