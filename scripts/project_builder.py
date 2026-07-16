#!/usr/bin/env python3
"""Create a runnable local project from the files supplied to an agent.

This is intentionally a compiler input builder, not a data downloader.  It
keeps all paths local and makes the classification method explicit: imagery
alone cannot supply either a trained neural model or supervised ROI samples.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _local(path: str | None) -> str | None:
    return str(Path(path).expanduser().resolve()) if path else None


def build(project_file: Path, project_id: str, workspace: str, imagery_periods: list[dict[str, Any]],
          driver_factors: dict[str, Any], mine_boundary: str, carbon_density: str, *, w_dat: str | None = None,
          model_package: str | None = None, training_roi: str | None = None, scheme: str = "high_water_coal_7class",
          w_dat_unit: str | None = None, w_dat_convention: str | None = None,
          workface_boundary: str | None = None, w_dat_max_distance_m: float = 300.0,
          subsidence_depth_raster: str | None = None) -> dict[str, Any]:
    if not imagery_periods or len(imagery_periods) < 2:
        raise ValueError("automatic PLUS workflow needs at least two dated imagery_periods")
    if bool(model_package) == bool(training_roi):
        raise ValueError("provide exactly one of model_package (PyTorch) or training_roi (ENVI supervised classification)")
    if scheme not in {"standard_6class", "high_water_coal_7class"}:
        raise ValueError("scheme must be standard_6class or high_water_coal_7class")
    normalized_periods: list[dict[str, Any]] = []
    for item in imagery_periods:
        if not isinstance(item, dict) or not isinstance(item.get("year"), int) or not isinstance(item.get("path"), str):
            raise ValueError("each imagery period requires integer year and local path")
        normalized_periods.append({"year": item["year"], "path": _local(item["path"])})
    normalized_periods.sort(key=lambda item: item["year"])
    factor_paths = [value.get("path") if isinstance(value, dict) else value for value in driver_factors.values()]
    roots = sorted({str(Path(value).expanduser().resolve().parent) for value in [
        *[item["path"] for item in normalized_periods], *factor_paths, mine_boundary, carbon_density,
        w_dat, subsidence_depth_raster, model_package, training_roi, workface_boundary] if value})
    project_root = project_file.expanduser().resolve().parent
    payload: dict[str, Any] = {
        "schema_version": 2, "project_id": project_id, "workspace": workspace,
        "security": {"input_roots": roots, "output_root": str((project_root / workspace).resolve().parent)},
        "inputs": {"imagery_periods": normalized_periods, "imagery": [], "mine_boundary": _local(mine_boundary),
                   "carbon_density": _local(carbon_density), "historical_lulc": [], "lulc_baseline": None,
                   "model_package": _local(model_package), "training_roi": _local(training_roi), "subsidence_w_dat": _local(w_dat),
                   "subsidence_depth_raster": _local(subsidence_depth_raster), "dem": _local(driver_factors.get("dem", {}).get("path") if isinstance(driver_factors.get("dem"), dict) else driver_factors.get("dem")),
                   "workface_boundary": _local(workface_boundary),
                   "driver_factors": {key: ({**value, "path": _local(value.get("path"))} if isinstance(value, dict) else _local(value)) for key, value in driver_factors.items()}},
        "classification": {"enabled": True, "engine": "pytorch" if model_package else "envi", "scheme": scheme,
                           "output_lulc": "outputs/lulc/LULC_{year}.tif", "output_confidence": "outputs/lulc/confidence_{year}.tif",
                           "envi_method": "maximum_likelihood", "accuracy": {"enabled": False}},
        "plus": {"enabled": True, "baseline_year": normalized_periods[-1]["year"], "target_year": normalized_periods[-1]["year"] + 5,
                 "scenarios": ["ND", "UD", "EP", "RE"], "output_workspace": "outputs/plus",
                 "resource_extraction": {"core_driver": "subsidence_depth", "core_driver_input": "inputs.subsidence_depth_raster",
                     "core_driver_unit": "m", "core_driver_convention": "positive_down", "requires_master_grid_alignment": True,
                     "additional_driver_factors": [name for name in ("dem", "slope", "road_distance", "mine_distance") if driver_factors.get(name)],
                     "w_dat_preprocessing": {"source_unit": w_dat_unit, "source_convention": w_dat_convention,
                         "output_depth_unit": "m", "output_depth_convention": "positive_down",
                         "interpolation": "nearest_within_scope", "scope_vector": _local(workface_boundary) or _local(mine_boundary),
                         "max_interpolation_distance_m": w_dat_max_distance_m}}},
        "invest": {"enabled": True, "output_workspace": "outputs/invest", "models": {"carbon": {"enabled": True, "service_unit": "Mg C"}}},
        "subsidence_water": {"enabled": False, "mode": "classify_only"},
        "ecosystem_service": {"enabled": False, "method": "minmax"},
        "gis_outputs": {"enabled": False},
        "validation": {"enabled": True, "output_report": "validation/analysis_validation_report.json"},
    }
    project_file = project_file.expanduser().resolve(); project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "completed", "project_file": str(project_file), "project_id": project_id,
            "classification_engine": payload["classification"]["engine"], "imagery_years": [item["year"] for item in normalized_periods],
            "pending_inputs": (["choose_one_subsidence_input"] if w_dat and subsidence_depth_raster else []) +
                              (["w_dat_unit_and_convention"] if w_dat and (not w_dat_unit or not w_dat_convention) else []) +
                              (["w_dat_max_distance_m"] if w_dat and (not isinstance(w_dat_max_distance_m, (int, float)) or w_dat_max_distance_m <= 0) else []) +
                              ["annual_water_yield_and_habitat_parameter_datastacks"]}
