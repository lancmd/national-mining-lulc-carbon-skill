#!/usr/bin/env python3
"""Collect local validation artifacts into one conditional analysis-evidence file."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def first(workspace: Path, patterns: list[str]) -> dict[str, Any] | None:
    for pattern in patterns:
        for path in sorted(workspace.glob(pattern)):
            payload = read_json(path)
            if payload is not None:
                return payload
    return None


def lulc_evidence(workspace: Path) -> dict[str, Any] | None:
    """Adapt the accuracy tool's native report to the analysis-validation contract."""
    report = first(workspace, ["validation/lulc_accuracy.json", "**/lulc_accuracy*.json"])
    if not report:
        return None
    if isinstance(report.get("metrics"), dict):
        return report
    required = {"oa", "f1", "iou", "classes"}
    if required.issubset(report):
        return {"metrics": {name: report[name] for name in required}, "source": report.get("output")}
    return report


def sensitivity_evidence(workspace: Path) -> dict[str, Any]:
    """Report sensitivity only after a non-empty, parseable result is available."""
    for path in sorted(workspace.glob("outputs/**/sensitivity*.csv")):
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            shifts = [float(row["max_rank_shift"]) for row in rows if row.get("max_rank_shift") not in (None, "")]
            if rows and shifts and all(value >= 0 for value in shifts):
                return {"available": True, "record_count": len(rows), "maximum_rank_shift": max(shifts),
                        "output": str(path.resolve())}
        except (OSError, ValueError, KeyError):
            continue
    return {"available": False}


def invest_evidence(workspace: Path) -> dict[str, Any] | None:
    carbon = first(workspace, ["validation/invest_consistency*.json", "**/*invest*consistency*.json"])
    job = first(workspace, ["generated/workflow_job.json", "generated/workflow_job*.json"])
    state = first(workspace, ["agent_state.json"])
    if not carbon and not job:
        return None
    evidence: dict[str, Any] = {"carbon": carbon or {}}
    stage_state = state.get("stages", {}) if isinstance(state, dict) else {}
    models: dict[str, Any] = {}
    for stage in job.get("stages", []) if isinstance(job, dict) else []:
        identifier = str(stage.get("id", ""))
        model = str(stage.get("model", ""))
        if not identifier.startswith("invest_") or not model or model == "carbon":
            continue
        record = stage_state.get(identifier, {}) if isinstance(stage_state, dict) else {}
        declared = [str(item) for item in stage.get("outputs", []) if isinstance(item, str)]
        scenario = identifier.removeprefix(f"invest_{model}").lstrip("_") or "baseline"
        models.setdefault(model, {"scenarios": {}})["scenarios"][scenario] = {
            "status": record.get("status", "pending_validation"), "outputs": declared,
            "units": {str(stage.get("service_field", "value")): stage.get("service_unit", "")},
        }
    if models:
        evidence["models"] = models
    return evidence


def subsidence_water_evidence(workspace: Path) -> dict[str, Any] | None:
    for path in sorted(workspace.glob("validation/subsidence_water_classification*.json")):
        report = read_json(path)
        if report and report.get("mode") == "classify_only":
            return report | {"source": str(path.resolve())}
    required = ("water_volume_m3", "subsidence_water_composite_carbon_t_c")
    for path in sorted(workspace.glob("outputs/**/*.csv")):
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream), None)
            if row and all(field in row for field in required):
                return {field: float(row[field]) for field in required} | {"mode": "composite_subsidence_water_carbon", "source": str(path.resolve())}
            if row and "water_volume_m3" in row:
                return {"water_volume_m3": float(row["water_volume_m3"]), "mode": "estimate_volume", "source": str(path.resolve())}
        except (OSError, ValueError, StopIteration):
            continue
    return None


def ecosystem_evidence(workspace: Path) -> dict[str, Any] | None:
    metadata = first(workspace, ["outputs/**/*.metadata.json", "validation/**/ecosystem*.json"])
    if not metadata or "normalization_bounds" not in metadata:
        return None
    evidence: dict[str, Any] = {"method": metadata.get("method"),
        "normalised_ranges": {name: [0.0, 1.0] for name in metadata.get("criteria", [])},
        "ahp_consistency_ratio": metadata.get("consistency_ratio"),
        "sensitivity": sensitivity_evidence(workspace),
        "metadata": metadata}
    return evidence


def assemble(workspace: Path, required_sections: list[str], output: Path) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    if "lulc" in required_sections:
        reports["lulc"] = lulc_evidence(workspace) or {}
    if "plus" in required_sections:
        reports["plus"] = first(workspace, ["validation/plus_validation*.json", "**/*plus*validation*.json"]) or {}
    if "invest" in required_sections:
        reports["invest"] = invest_evidence(workspace) or {}
    if "ecosystem" in required_sections:
        reports["ecosystem"] = ecosystem_evidence(workspace) or {}
    if "subsidence_water" in required_sections:
        reports["subsidence_water"] = subsidence_water_evidence(workspace) or {}
    if "map" in required_sections:
        reports["map"] = first(workspace, ["validation/map_layout.json"]) or {}
    payload = {"schema_version": 1, "required_sections": required_sections, "reports": reports}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "completed", "output": str(output.resolve()), "required_sections": required_sections,
            "evidence_sections": sorted(name for name, value in reports.items() if value)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--required-sections", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    sections = [item.strip() for item in args.required_sections.split(",") if item.strip()]
    print(json.dumps(assemble(args.workspace.resolve(), sections, args.output.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
