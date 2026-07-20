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


TASK_TYPES = {
    "classification_only", "lulc_change_analysis", "plus_only", "invest_only",
    "ecosystem_service_only", "mapping_only", "full_chain",
}


def _local(path: str | None) -> str | None:
    return str(Path(path).expanduser().resolve()) if path else None


def build(project_file: Path, project_id: str, workspace: str, imagery_periods: list[dict[str, Any]] | None = None,
          driver_factors: dict[str, Any] | None = None, mine_boundary: str | None = None,
          carbon_density: str | None = None, *, task_type: str = "full_chain",
          historical_lulc_periods: list[dict[str, Any]] | None = None,
          ecosystem_criteria: str | None = None, ecosystem_config: str | None = None,
          gis_outputs: dict[str, Any] | None = None, w_dat: str | None = None,
          model_package: str | None = None, training_roi: str | None = None, scheme: str = "high_water_coal_7class",
          w_dat_unit: str | None = None, w_dat_convention: str | None = None,
          workface_boundary: str | None = None, w_dat_max_distance_m: float = 300.0,
          subsidence_depth_raster: str | None = None, patch_size: int | None = None,
          patch_stride: int | None = None, patch_band_indexes: list[int] | None = None,
          patch_input_scale: float | None = None, patch_batch_size: int | None = None,
          allow_patch_grid_as_lulc: bool = False) -> dict[str, Any]:
    if task_type not in TASK_TYPES:
        raise ValueError("task_type must be one of " + ", ".join(sorted(TASK_TYPES)))
    imagery_periods = imagery_periods or []
    historical_lulc_periods = historical_lulc_periods or []
    driver_factors = driver_factors or {}
    requires_classification = task_type in {"classification_only", "full_chain"}
    requires_history = task_type in {"lulc_change_analysis", "plus_only"}
    requires_plus = task_type in {"plus_only", "full_chain"}
    if requires_classification and not imagery_periods:
        raise ValueError(f"{task_type} requires one or more dated imagery_periods")
    if requires_plus and len(imagery_periods if requires_classification else historical_lulc_periods) < 2:
        raise ValueError(f"{task_type} requires at least two dated LULC sources")
    if requires_history and len(historical_lulc_periods) < 2:
        raise ValueError(f"{task_type} requires at least two historical_lulc_periods")
    if task_type == "invest_only" and not historical_lulc_periods:
        raise ValueError("invest_only requires at least one historical_lulc_period")
    if task_type == "ecosystem_service_only" and (not ecosystem_criteria or not ecosystem_config):
        raise ValueError("ecosystem_service_only requires ecosystem_criteria and ecosystem_config")
    if task_type == "mapping_only" and not isinstance(gis_outputs, dict):
        raise ValueError("mapping_only requires a gis_outputs object")
    if requires_classification and bool(model_package) == bool(training_roi):
        raise ValueError("classification requires exactly one of model_package (PyTorch) or training_roi (ENVI supervised classification)")
    if scheme not in {"standard_6class", "high_water_coal_7class"}:
        raise ValueError("scheme must be standard_6class or high_water_coal_7class")
    native_patch_model = bool(model_package and (Path(model_package).expanduser() / "model" / "model.json").is_file())
    if native_patch_model and scheme == "high_water_coal_7class":
        # This model has one water class, so high-water seven-class output would be false precision.
        scheme = "standard_6class"
    normalized_periods: list[dict[str, Any]] = []
    for item in imagery_periods:
        if not isinstance(item, dict) or not isinstance(item.get("year"), int) or not isinstance(item.get("path"), str):
            raise ValueError("each imagery period requires integer year and local path")
        normalized_periods.append({"year": item["year"], "path": _local(item["path"])})
    normalized_periods.sort(key=lambda item: item["year"])
    normalized_lulc: list[dict[str, Any]] = []
    for item in historical_lulc_periods:
        if not isinstance(item, dict) or not isinstance(item.get("year"), int) or not isinstance(item.get("path"), str):
            raise ValueError("each historical LULC period requires integer year and local path")
        normalized_lulc.append({"year": item["year"], "path": _local(item["path"])})
    normalized_lulc.sort(key=lambda item: item["year"])
    factor_paths = [value.get("path") if isinstance(value, dict) else value for value in driver_factors.values()]
    roots = sorted({str(Path(value).expanduser().resolve().parent) for value in [
        *[item["path"] for item in normalized_periods], *[item["path"] for item in normalized_lulc], *factor_paths,
        mine_boundary, carbon_density, ecosystem_criteria, ecosystem_config, w_dat, subsidence_depth_raster,
        model_package, training_roi, workface_boundary] if value})
    if isinstance(gis_outputs, dict):
        for key in ("aprx",):
            if gis_outputs.get(key):
                roots.append(str(Path(str(gis_outputs[key])).expanduser().resolve().parent))
        for layer in gis_outputs.get("layers", []) if isinstance(gis_outputs.get("layers", []), list) else []:
            if isinstance(layer, dict):
                for key in ("path", "symbology_layer"):
                    if layer.get(key) and layer.get("source", "input") == "input":
                        roots.append(str(Path(str(layer[key])).expanduser().resolve().parent))
    project_root = project_file.expanduser().resolve().parent
    roots = sorted(set(roots)) or [str(project_root)]
    latest_year = (normalized_periods or normalized_lulc or [{"year": 0}])[-1]["year"]
    payload: dict[str, Any] = {
        "schema_version": 2, "project_id": project_id, "task_type": task_type, "workspace": workspace,
        "security": {"input_roots": roots, "output_root": str((project_root / workspace).resolve().parent)},
        "inputs": {"imagery_periods": normalized_periods, "imagery": [], "mine_boundary": _local(mine_boundary),
                   "carbon_density": _local(carbon_density), "historical_lulc": [item["path"] for item in normalized_lulc],
                   "lulc_baseline": normalized_lulc[-1]["path"] if normalized_lulc else None,
                   "model_package": _local(model_package), "training_roi": _local(training_roi), "subsidence_w_dat": _local(w_dat),
                   "subsidence_depth_raster": _local(subsidence_depth_raster), "dem": _local(driver_factors.get("dem", {}).get("path") if isinstance(driver_factors.get("dem"), dict) else driver_factors.get("dem")),
                   "workface_boundary": _local(workface_boundary),
                   "driver_factors": {key: ({**value, "path": _local(value.get("path"))} if isinstance(value, dict) else _local(value)) for key, value in driver_factors.items()}},
        "classification": {"enabled": requires_classification, "engine": "pytorch" if model_package else ("envi" if training_roi else "provided_lulc"), "scheme": scheme,
                           "output_lulc": "outputs/lulc/LULC_{year}.tif", "output_confidence": "outputs/lulc/confidence_{year}.tif",
                           "envi_method": "maximum_likelihood", "accuracy": {"enabled": False},
                           "patch_classifier": {"enabled": native_patch_model, "patch_size": patch_size, "stride": patch_stride,
                                                "band_indexes": patch_band_indexes, "input_scale": patch_input_scale,
                                                "batch_size": patch_batch_size, "allow_as_lulc": bool(allow_patch_grid_as_lulc)}},
        "plus": {"enabled": requires_plus,
                 "baseline_year": latest_year, "target_year": latest_year + 5,
                 "scenarios": ["ND", "UD", "EP", "RE"], "output_workspace": "outputs/plus",
                 "resource_extraction": {"core_driver": "subsidence_depth", "core_driver_input": "inputs.subsidence_depth_raster",
                     "core_driver_unit": "m", "core_driver_convention": "positive_down", "requires_master_grid_alignment": True,
                     "additional_driver_factors": [name for name in ("dem", "slope", "road_distance", "mine_distance") if driver_factors.get(name)],
                     "w_dat_preprocessing": {"source_unit": w_dat_unit, "source_convention": w_dat_convention,
                         "output_depth_unit": "m", "output_depth_convention": "positive_down",
                         "interpolation": "nearest_within_scope", "scope_vector": _local(workface_boundary) or _local(mine_boundary),
                         "max_interpolation_distance_m": w_dat_max_distance_m}}},
        "invest": {"enabled": task_type in {"invest_only", "full_chain"}, "output_workspace": "outputs/invest", "models": {"carbon": {"enabled": True, "service_unit": "Mg C"}}},
        "subsidence_water": {"enabled": False, "mode": "classify_only"},
        "ecosystem_service": {"enabled": task_type == "ecosystem_service_only", "method": "minmax",
                              "criteria_table": _local(ecosystem_criteria), "config": _local(ecosystem_config)},
        "gis_outputs": {"enabled": task_type == "mapping_only", **(gis_outputs or {})},
        "validation": {"enabled": True, "output_report": "validation/analysis_validation_report.json"},
    }
    if normalized_lulc:
        payload["inputs"]["historical_lulc_periods"] = normalized_lulc
    project_file = project_file.expanduser().resolve(); project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "completed", "project_file": str(project_file), "project_id": project_id,
            "task_type": task_type, "classification_engine": payload["classification"]["engine"],
            "model_mode": "registered_resnet50_patch_classifier" if native_patch_model else "segmentation_or_envi",
            "imagery_years": [item["year"] for item in normalized_periods],
            "pending_inputs": (["choose_one_subsidence_input"] if w_dat and subsidence_depth_raster else []) +
                              (["w_dat_unit_and_convention"] if w_dat and (not w_dat_unit or not w_dat_convention) else []) +
                              (["w_dat_max_distance_m"] if w_dat and (not isinstance(w_dat_max_distance_m, (int, float)) or w_dat_max_distance_m <= 0) else []) +
                              (["resnet50_patch_size_stride_rgb_scale"] if native_patch_model and
                               (not isinstance(patch_size, int) or not isinstance(patch_stride, int) or
                                not isinstance(patch_band_indexes, list) or not isinstance(patch_input_scale, (int, float))) else []) +
                              (["resnet50_patch_grid_full_chain_confirmation_and_accuracy"] if native_patch_model and task_type == "full_chain" else []) +
                              (["annual_water_yield_and_habitat_parameter_datastacks"] if task_type == "full_chain" else [])}
