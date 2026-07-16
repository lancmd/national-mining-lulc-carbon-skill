#!/usr/bin/env python3
"""Compile one validated local project into a resumable, local workflow job."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from path_safety import PathSafetyError, require_within, resolved, resolve_output
from plus_contract import canonical_re_contract, expected_plus_raster
from project_validator import validate
from spatial_contract import parse_driver_factors


ROOT = Path(__file__).resolve().parents[1]
INVEST_MODELS = {
    "carbon": {"cli": "carbon", "lulc_argument": "lulc_cur_path", "default_output": "tot_c_cur.tif",
               "service_field": "carbon_storage_t_c", "service_aggregation": "sum"},
    "annual_water_yield": {"cli": "annual_water_yield", "lulc_argument": "lulc_path", "default_output": None,
                            "service_field": "water_yield_m3", "service_aggregation": "depth_mm_to_m3"},
    "habitat_quality": {"cli": "habitat_quality", "lulc_argument": "lulc_cur_path", "default_output": None,
                        "service_field": "habitat_quality", "service_aggregation": "mean"},
    "sediment_delivery_ratio": {"cli": "sdr", "lulc_argument": "lulc_path", "default_output": None,
                                  "service_field": "sediment_retention", "service_aggregation": "sum"},
    "nutrient_delivery_ratio": {"cli": "ndr", "lulc_argument": "lulc_path", "default_output": None,
                                  "service_field": "nutrient_retention", "service_aggregation": "sum"},
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_path(value: str | None, base: Path) -> str | None:
    return str(resolved(value, base)) if value else None


def output_path(value: str, workspace: Path) -> str:
    return str(resolve_output(value, workspace))


def map_layer_definition(value: dict[str, Any], base: Path) -> dict[str, Any]:
    """Resolve map resource paths relative to project.json before ArcGIS changes cwd."""
    result = dict(value)
    for key in ("path", "symbology_layer"):
        if result.get(key):
            result[key] = source_path(result[key], base)
    return result


def carbon_datastack(lulc: str, carbon_table: str, output: Path) -> str:
    write_json(output, {"args": {"calc_sequestration": False, "carbon_pools_path": carbon_table,
        "do_redd": False, "do_valuation": False, "lulc_cur_path": lulc, "n_workers": -1,
        "results_suffix": ""}, "model_name": "natcap.invest.carbon"})
    return str(output)


def enabled_invest_models(invest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    configured = invest.get("models")
    if not isinstance(configured, dict) or not configured:
        return {"carbon": {"enabled": True, "provided_datastack": invest.get("datastack")}}
    return {name: value for name, value in configured.items()
            if name in INVEST_MODELS and isinstance(value, dict) and value.get("enabled")}


def scenario_datastack(model: str, config: dict[str, Any], lulc: str, carbon_table: str | None,
                       base: Path, output: Path) -> str:
    """Clone a model template once per scenario and replace only the LULC argument."""
    template_value = config.get("datastack_template") or config.get("provided_datastack")
    if template_value:
        template = Path(source_path(str(template_value), base) or "")
        payload = read_json(template)
        args = payload.setdefault("args", {})
        if not isinstance(args, dict):
            raise ValueError(f"InVEST {model} datastack args must be an object")
        # Datastack templates are often stored beside parameter CSVs.  They
        # are cloned into workspace/generated, so make their local references
        # absolute before cloning rather than breaking relative table paths.
        for key, value in list(args.items()):
            if isinstance(value, str) and (key.endswith("_path") or key.endswith("_table_path") or key.endswith("_vector_path")):
                candidate = Path(value).expanduser()
                if not candidate.is_absolute():
                    args[key] = str((template.parent / candidate).resolve())
        args[config.get("lulc_argument", INVEST_MODELS[model]["lulc_argument"])] = lulc
        write_json(output, payload)
        return str(output)
    if model != "carbon":
        raise ValueError(f"InVEST {model} requires datastack_template or provided_datastack")
    if not carbon_table:
        raise ValueError("generated InVEST carbon datastack requires inputs.carbon_density")
    return carbon_datastack(lulc, carbon_table, output)


def allowed_codes(scheme: str) -> list[int]:
    return list(range(1, 8 if scheme == "high_water_coal_7class" else 7))


def configured_imagery_periods(inputs: dict[str, Any], base: Path) -> list[tuple[int, str]]:
    """Return explicitly dated imagery, falling back to the legacy image list.

    The fallback is suitable for a one-date classification only.  PLUS callers
    are validated to use the explicit form because chronological order matters.
    """
    raw = inputs.get("imagery_periods")
    if isinstance(raw, list) and raw:
        return [(int(item["year"]), source_path(str(item["path"]), base) or "") for item in raw]
    return [(index + 1, source_path(str(value), base) or "") for index, value in enumerate(inputs.get("imagery", [])) if value]


def configured_lulc_periods(inputs: dict[str, Any], base: Path) -> list[tuple[int, str]]:
    """Read dated supplied LULC products while retaining legacy list support."""
    periods = inputs.get("historical_lulc_periods")
    if isinstance(periods, list) and periods:
        return [(int(item["year"]), source_path(str(item["path"]), base) or "") for item in periods]
    return [(index + 1, source_path(str(value), base) or "")
            for index, value in enumerate(inputs.get("historical_lulc", [])) if value]


def templated_output(value: str | None, default: str, year: int, workspace: Path, multi: bool) -> str:
    """Keep a legacy single-date output stable and make multi-date outputs unique."""
    if value and "{year}" in value:
        return output_path(value.format(year=year), workspace)
    if multi:
        configured = Path(value or default)
        suffix = configured.suffix or ".tif"
        stem = configured.stem or "LULC"
        return output_path(str(Path("outputs") / "lulc" / f"{stem}_{year}{suffix}"), workspace)
    return output_path(value or default, workspace)


def add_preflight(stages: list[dict[str, Any]], workspace: Path, inputs: dict[str, Any], base: Path,
                  classification: dict[str, Any], plus: dict[str, Any], subsidence: dict[str, Any]) -> str | None:
    datasets: list[dict[str, Any]] = []
    scheme = classification.get("scheme", "standard_6class")
    historical = [source_path(item, base) for item in inputs.get("historical_lulc", []) if item]
    baseline = source_path(inputs.get("lulc_baseline"), base)
    periods = configured_imagery_periods(inputs, base)
    imagery = [path for _, path in periods]
    automatic_history = classification.get("enabled") and classification.get("engine") != "provided_lulc" and len(inputs.get("imagery_periods", [])) >= 2
    master: str | None = None
    if plus.get("enabled") and historical:
        master = "historical_lulc_latest"
        for index, path in enumerate(historical):
            datasets.append({"name": "historical_lulc_latest" if index == len(historical) - 1 else f"historical_lulc_{index + 1}",
                             "path": path, "kind": "lulc", "allowed_codes": allowed_codes(scheme), "must_align": True})
    elif baseline:
        master = "lulc_baseline"
        datasets.append({"name": master, "path": baseline, "kind": "lulc", "allowed_codes": allowed_codes(scheme), "must_align": True})
    elif classification.get("enabled") and imagery:
        master = "imagery_latest"
        image_spec: dict[str, Any] = {"name": master, "path": imagery[-1], "kind": "continuous", "must_align": False}
        if classification.get("engine") == "pytorch" and inputs.get("model_package"):
            try:
                model = read_json(Path(source_path(inputs["model_package"], base)) / "model_config.json")
                model_input = model.get("input", {})
                image_spec.update({"expected_band_count": len(model_input.get("band_indexes", [])),
                                   "expected_band_names": model_input.get("bands"),
                                   "expected_value_range": model_input.get("value_range"),
                                   "sensor": model_input.get("sensor")})
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        datasets.append(image_spec)
        # Classifiers can consume native grids.  Their discrete outputs are
        # subsequently aligned to the latest LULC grid before change analysis.
        for year, image in periods[:-1]:
            datasets.append({"name": f"imagery_{year}", "path": image, "kind": "continuous", "must_align": False})
    if plus.get("enabled"):
        for name, entry in parse_driver_factors(inputs.get("driver_factors", {})).items():
            if entry:
                # Raw factors may legitimately use another CRS/resolution.
                # A later ArcGIS stage creates the aligned working copies and
                # a second preflight verifies those copies before PLUS.
                datasets.append({"name": f"driver_{name}", "path": source_path(entry["path"], base),
                                 "kind": "continuous" if entry["type"] != "categorical" else "categorical",
                                 "must_align": False})
        if inputs.get("subsidence_depth_raster"):
            datasets.append({"name": "subsidence_depth", "path": source_path(inputs["subsidence_depth_raster"], base),
                             "kind": "subsidence_depth", "must_align": False,
                             "require_projected_meters": bool(subsidence.get("enabled"))})
    if subsidence.get("enabled") and subsidence.get("mode") in {"estimate_volume", "composite_subsidence_water_carbon"}:
        for name, value, kind in (("dem", inputs.get("dem"), "continuous"),
                                  ("subsidence_depth", inputs.get("subsidence_depth_raster"), "subsidence_depth")):
            if value and not any(item["name"] == name for item in datasets):
                datasets.append({"name": name, "path": source_path(value, base), "kind": kind, "must_align": bool(master),
                                 "require_projected_meters": kind in {"continuous", "subsidence_depth"}})
    for name, value in (("mine_boundary", inputs.get("mine_boundary")), ("training_roi", inputs.get("training_roi")),
                        ("subsidence_water_boundary", inputs.get("subsidence_water_boundary"))):
        if value:
            datasets.append({"name": name, "path": source_path(value, base), "kind": "vector", "require_crs": True})
    if not datasets:
        return None
    vertical_datum: dict[str, Any] = {}
    if subsidence.get("enabled") and subsidence.get("mode") in {"estimate_volume", "composite_subsidence_water_carbon"}:
        vertical_datum = {"dem": inputs.get("elevation_vertical_datum"),
                          "water_level": subsidence.get("water_level_vertical_datum")}
    spec = {"master": master, "datasets": datasets, "carbon_density": source_path(inputs.get("carbon_density"), base),
            "vertical_datum": vertical_datum}
    spec_path = workspace / "generated" / "spatial_preflight.json"
    report = workspace / "validation" / "spatial_preflight.json"
    write_json(spec_path, spec)
    stages.append({"id": "spatial_preflight", "adapter": "command", "enabled": True,
                   "command": [sys.executable, str(ROOT / "scripts" / "spatial_preflight.py"), "--spec", str(spec_path),
                               "--output", str(report)], "inputs": [item["path"] for item in datasets],
                   "outputs": [str(report)], "depends_on": []})
    return "spatial_preflight"


def lulc_validation_stage(stages: list[dict[str, Any],], identifier: str, lulc: str, master: str | None,
                          scheme: str, carbon: str | None, workspace: Path, dependencies: list[str]) -> str:
    spec = {"master": "master" if master else "lulc", "datasets": [
        {"name": "master", "path": master, "kind": "continuous", "must_align": False}] if master else []}
    spec["datasets"].append({"name": "lulc", "path": lulc, "kind": "lulc", "allowed_codes": allowed_codes(scheme),
                             "must_align": bool(master)})
    spec["carbon_density"] = carbon
    spec_path = workspace / "generated" / f"{identifier}.json"
    report = workspace / "validation" / f"{identifier}.json"
    write_json(spec_path, spec)
    stages.append({"id": identifier, "adapter": "command", "enabled": True,
                   "command": [sys.executable, str(ROOT / "scripts" / "spatial_preflight.py"), "--spec", str(spec_path),
                               "--output", str(report)], "inputs": [lulc] + ([master] if master else []) + ([carbon] if carbon else []),
                   "outputs": [str(report)], "depends_on": dependencies})
    return identifier


def historical_lulc_validation_stage(stages: list[dict[str, Any]], identifier: str, history: list[tuple[int, str]],
                                     scheme: str, carbon: str | None, workspace: Path,
                                     dependencies: list[str]) -> str:
    """Assert all dated LULC products are pixel-identical before PLUS/Sankey."""
    latest_year, latest = history[-1]
    datasets = [{"name": f"lulc_{year}", "path": path, "kind": "lulc", "allowed_codes": allowed_codes(scheme),
                 "must_align": True, "expected_cell_size_m": 30} for year, path in history]
    datasets[-1]["name"] = "master_lulc"
    spec = {"master": "master_lulc", "datasets": datasets, "carbon_density": carbon}
    spec_path = workspace / "generated" / f"{identifier}.json"; report = workspace / "validation" / f"{identifier}.json"
    write_json(spec_path, spec)
    stages.append({"id": identifier, "adapter": "command", "enabled": True,
                   "command": [sys.executable, str(ROOT / "scripts" / "spatial_preflight.py"), "--spec", str(spec_path),
                               "--output", str(report)], "inputs": [path for _, path in history] + ([carbon] if carbon else []),
                   "outputs": [str(report)], "depends_on": dependencies})
    return identifier


def add_transition_sankeys(stages: list[dict[str, Any]], history: list[tuple[int, str]], scheme: str,
                           workspace: Path, dependencies: list[str]) -> list[str]:
    results: list[str] = []
    for (old_year, old), (new_year, new) in zip(history, history[1:]):
        stem = f"{old_year}_{new_year}"
        table = str(workspace / "outputs" / "transitions" / f"LULC_transition_{stem}.csv")
        figure = str(workspace / "outputs" / "figures" / f"LULC_Sankey_{stem}.svg")
        stage_id = f"lulc_sankey_{old_year}_{new_year}"
        stages.append({"id": stage_id, "adapter": "command", "enabled": True,
                       "command": [sys.executable, str(ROOT / "scripts" / "lulc_transition_sankey.py"),
                                   "--from-raster", old, "--to-raster", new, "--from-year", str(old_year),
                                   "--to-year", str(new_year), "--scheme", scheme, "--output-csv", table,
                                   "--output-svg", figure],
                       "inputs": [old, new], "outputs": [table, table + ".metadata.json", figure],
                       "depends_on": dependencies.copy()})
        results.append(stage_id)
    return results


def add_raster_map(stages: list[dict[str, Any]], identifier: str, raster: str, title: str, kind: str,
                   scheme: str, workspace: Path, dependencies: list[str]) -> str:
    output = str(workspace / "outputs" / "figures" / f"{identifier}.svg")
    stages.append({"id": f"map_{identifier}", "adapter": "command", "enabled": True,
                   "command": [sys.executable, str(ROOT / "scripts" / "raster_map_svg.py"), "--raster", raster,
                               "--output", output, "--title", title, "--kind", kind, "--scheme", scheme],
                   "inputs": [raster], "outputs": [output], "depends_on": dependencies.copy()})
    return f"map_{identifier}"


def compile_workflow(project_path: Path, output_job: Path | None = None) -> dict[str, Any]:
    project_path = project_path.expanduser().resolve()
    report = validate(project_path)
    if report["status"] != "valid":
        raise ValueError("project validation failed: " + "; ".join(report["errors"]))
    project, base, workspace = read_json(project_path), project_path.parent, Path(report["workspace"]).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    output_job = output_job.expanduser().resolve() if output_job else workspace / "generated" / "workflow_job.json"
    try:
        require_within(output_job, [workspace], "workflow job")
    except PathSafetyError as error:
        raise ValueError("workflow_job must be written inside the project workspace") from error
    inputs = project["inputs"]
    classification, plus, invest = project.get("classification", {}), project.get("plus", {}), project.get("invest", {})
    subsidence, ecosystem = project.get("subsidence_water", {}), project.get("ecosystem_service", {})
    gis_outputs, validation_config = project.get("gis_outputs", {}), project.get("validation", {})
    stages: list[dict[str, Any]] = []
    preflight = add_preflight(stages, workspace, inputs, base, classification, plus, subsidence)
    dependencies = [preflight] if preflight else []
    carbon = source_path(inputs.get("carbon_density"), base)
    lulc: str | None = source_path(inputs.get("lulc_baseline"), base)
    lulc_dependency = dependencies.copy()

    lulc_history: list[tuple[int, str]] = []
    if classification.get("enabled"):
        # A supplied LULC is an analysis input.  A classifier, in contrast,
        # runs once per explicitly dated image and never overwrites an earlier
        # date's product.
        engine, scheme = classification["engine"], classification["scheme"]
        periods = configured_imagery_periods(inputs, base)
        if engine == "provided_lulc":
            lulc = source_path(inputs["lulc_baseline"], base)
            lulc_dependency = [lulc_validation_stage(stages, "lulc_output_validation", lulc, None,
                                                      scheme, carbon, workspace, dependencies.copy())]
        else:
            multi = len(periods) > 1
            raw_history: list[tuple[int, str, str]] = []
            for year, image in periods:
                lulc_output = templated_output(classification.get("output_lulc"), "outputs/lulc.tif", year, workspace, multi)
                suffix = f"_{year}" if multi else ""
                if engine == "pytorch":
                    confidence = templated_output(classification.get("output_confidence"), "outputs/lulc_confidence.tif", year, workspace, multi)
                    low_confidence = (templated_output(classification.get("output_low_confidence"), "outputs/lulc_low_confidence.tif", year, workspace, multi)
                                      if classification.get("output_low_confidence") else None)
                    stage_id = f"classification_pytorch{suffix}"
                    command = [sys.executable, str(ROOT / "scripts" / "pytorch_lulc.py"), "infer", "--model-package",
                               source_path(inputs["model_package"], base), "--input-raster", image,
                               "--class-output", lulc_output, "--confidence-output", confidence]
                    if low_confidence:
                        command += ["--low-confidence-output", low_confidence]
                    if classification.get("low_confidence_threshold") is not None:
                        command += ["--low-confidence-threshold", str(classification["low_confidence_threshold"])]
                    stages.append({"id": stage_id, "adapter": "command", "enabled": True, "command": command,
                                   "inputs": [source_path(inputs["model_package"], base), image],
                                   "outputs": [item for item in [lulc_output, confidence, low_confidence] if item],
                                   "depends_on": dependencies.copy()})
                else:
                    method = classification.get("envi_method", "maximum_likelihood")
                    stage_id = f"classification_envi{suffix}"
                    stages.append({"id": stage_id, "adapter": "envi", "enabled": True,
                                   "batch_file": str(ROOT / "scripts" / ("envi_maximum_likelihood.pro" if method == "maximum_likelihood" else "envi_minimum_distance.pro")),
                                   "entrypoint": "mining_envi_maximum_likelihood" if method == "maximum_likelihood" else "mining_envi_minimum_distance",
                                   "env": {"MINING_INPUT_RASTER": image, "MINING_TRAINING_VECTOR": source_path(inputs["training_roi"], base),
                                           "MINING_OUTPUT_RASTER": lulc_output},
                                   "inputs": [image, source_path(inputs["training_roi"], base)], "outputs": [lulc_output],
                                   "depends_on": dependencies.copy()})
                validation_id = lulc_validation_stage(stages, f"lulc_output_validation{suffix}", lulc_output, image,
                                                      scheme, carbon, workspace, [stage_id])
                add_raster_map(stages, f"LULC_{year}", lulc_output, f"Land use / land cover {year}", "lulc", scheme,
                               workspace, [validation_id])
                raw_history.append((year, lulc_output, validation_id))
            latest_year, latest_lulc, latest_validation = raw_history[-1]
            # The analysis grid is intentionally fixed at 30 m even if the
            # classifier receives 10 m Sentinel imagery.  Categorical data is
            # reduced by modal (majority) aggregation, never by interpolation.
            master_lulc = str(workspace / "intermediate" / "master_lulc_30m.tif")
            stages.append({"id": "analysis_master_grid", "adapter": "command", "enabled": True,
                           "command": [sys.executable, str(ROOT / "scripts" / "raster_grid.py"), "--input", latest_lulc,
                                       "--output", master_lulc, "--cell-size-m", "30", "--kind", "categorical", "--resampling", "majority"],
                           "inputs": [latest_lulc], "outputs": [master_lulc, master_lulc + ".metadata.json"],
                           "depends_on": [latest_validation]})
            lulc, lulc_dependency = master_lulc, ["analysis_master_grid"]
            latest_aligned = output_path(f"outputs/lulc/aligned/LULC_{latest_year}.tif", workspace)
            stages.append({"id": f"align_lulc_{latest_year}", "adapter": "command", "enabled": True,
                           "command": [sys.executable, str(ROOT / "scripts" / "raster_grid.py"), "--input", master_lulc,
                                       "--master", master_lulc, "--output", latest_aligned, "--kind", "categorical", "--resampling", "majority"],
                           "inputs": [master_lulc], "outputs": [latest_aligned, latest_aligned + ".metadata.json"],
                           "depends_on": ["analysis_master_grid"]})
            lulc, lulc_history = latest_aligned, [(latest_year, latest_aligned)]
            alignment_dependencies: list[str] = [f"align_lulc_{latest_year}"]
            for year, raw_lulc, validation_id in raw_history[:-1]:
                aligned = output_path(f"outputs/lulc/aligned/LULC_{year}.tif", workspace)
                align_id = f"align_lulc_{year}"
                stages.append({"id": align_id, "adapter": "command", "enabled": True,
                               "command": [sys.executable, str(ROOT / "scripts" / "raster_grid.py"), "--input", raw_lulc,
                                           "--master", master_lulc, "--output", aligned, "--kind", "categorical", "--resampling", "majority"],
                               "inputs": [raw_lulc, master_lulc], "outputs": [aligned, aligned + ".metadata.json"],
                               "depends_on": [validation_id, "analysis_master_grid"]})
                lulc_history.insert(0, (year, aligned)); alignment_dependencies.append(align_id)
            if multi:
                history_validation = historical_lulc_validation_stage(stages, "historical_lulc_preflight", lulc_history,
                                                                       scheme, carbon, workspace, alignment_dependencies)
                lulc_dependency = [history_validation]
                add_transition_sankeys(stages, lulc_history, scheme, workspace, [history_validation])
        if not lulc_history and lulc:
            lulc_history = [(int(plus.get("baseline_year", 0) or 0), lulc)]
        # Independent accuracy data is optional, but when present it follows
        # the latest classified image automatically.
        accuracy = classification.get("accuracy", {})
        if accuracy.get("enabled"):
            acc_output = output_path(accuracy["output"], workspace); matrix = output_path(accuracy["confusion_matrix"], workspace)
            stages.append({"id": "lulc_accuracy", "adapter": "command", "enabled": True,
                           "command": [sys.executable, str(ROOT / "scripts" / "lulc_accuracy.py"), "--samples",
                                       source_path(accuracy["validation_samples"], base), "--reference-field", accuracy["reference_field"],
                                       "--prediction-field", accuracy["prediction_field"], "--output", acc_output,
                                       "--confusion-matrix", matrix] + (["--classification-raster", lulc, "--x-field", accuracy["x_field"],
                                       "--y-field", accuracy["y_field"]] if accuracy.get("x_field") and accuracy.get("y_field") else []) +
                                      (["--samples-crs", accuracy["samples_crs"]] if accuracy.get("samples_crs") else []),
                           "inputs": [source_path(accuracy["validation_samples"], base), lulc], "outputs": [acc_output, matrix],
                           "depends_on": lulc_dependency.copy()})
            lulc_dependency.append("lulc_accuracy")

    # Convert raw LULC products to the common 30 m analysis grid.  This covers
    # supplied historical maps as well as maps produced by a classifier above.
    provided_history = configured_lulc_periods(inputs, base)
    raw_history = lulc_history or provided_history
    if not raw_history and lulc:
        raw_history = [(int(plus.get("baseline_year", 0) or 0), lulc)]
    if raw_history and not any(stage["id"] == "analysis_master_grid" for stage in stages):
        latest_year, latest_source = raw_history[-1]
        master_lulc = str(workspace / "intermediate" / "master_lulc_30m.tif")
        stages.append({"id": "analysis_master_grid", "adapter": "command", "enabled": True,
                       "command": [sys.executable, str(ROOT / "scripts" / "raster_grid.py"), "--input", latest_source,
                                   "--output", master_lulc, "--cell-size-m", "30", "--kind", "categorical", "--resampling", "majority"],
                       "inputs": [latest_source], "outputs": [master_lulc, master_lulc + ".metadata.json"],
                       "depends_on": lulc_dependency.copy()})
        lulc_history = []
        alignment_ids: list[str] = []
        for year, raw in raw_history:
            aligned = output_path(f"outputs/lulc/aligned/LULC_{year}.tif", workspace)
            stage_id = f"align_lulc_{year}"
            stages.append({"id": stage_id, "adapter": "command", "enabled": True,
                           "command": [sys.executable, str(ROOT / "scripts" / "raster_grid.py"), "--input", raw,
                                       "--master", master_lulc, "--output", aligned, "--kind", "categorical", "--resampling", "majority"],
                           "inputs": [raw, master_lulc], "outputs": [aligned, aligned + ".metadata.json"],
                           "depends_on": ["analysis_master_grid"]})
            lulc_history.append((year, aligned)); alignment_ids.append(stage_id)
        lulc, lulc_dependency = lulc_history[-1][1], alignment_ids[-1:]
        if len(lulc_history) >= 2:
            history_validation = historical_lulc_validation_stage(stages, "historical_lulc_preflight", lulc_history,
                                                                   classification.get("scheme", "standard_6class"), carbon,
                                                                   workspace, alignment_ids)
            lulc_dependency = [history_validation]
            add_transition_sankeys(stages, lulc_history, classification.get("scheme", "standard_6class"), workspace,
                                   [history_validation])

    # Convert raw drivers and the PIM depth product into exact working copies
    # on the final LULC grid before PLUS or water-volume analysis begins.
    plus_history = lulc_history if len(lulc_history) >= 2 else (configured_lulc_periods(inputs, base) if len(configured_lulc_periods(inputs, base)) >= 2 else [])
    master_lulc = lulc_history[-1][1] if lulc_history else lulc
    driver_entries = parse_driver_factors(inputs.get("driver_factors", {}))
    prepared_drivers: dict[str, str] = {name: source_path(entry["path"], base) or "" for name, entry in driver_entries.items()}
    prepared_dependencies = lulc_dependency.copy() if lulc_dependency else dependencies.copy()
    subsidence_depth = source_path(inputs.get("subsidence_depth_raster"), base)
    if master_lulc and (plus.get("enabled") or subsidence.get("enabled")):
        mask = source_path(inputs.get("mine_boundary"), base)
        terrain_stage: str | None = None
        dem_source = source_path(inputs.get("dem"), base) or prepared_drivers.get("dem")
        if dem_source and ("slope" not in prepared_drivers or "aspect" not in prepared_drivers):
            raw_slope, raw_aspect = str(workspace / "outputs" / "drivers" / "slope_raw.tif"), str(workspace / "outputs" / "drivers" / "aspect_raw.tif")
            terrain_spec = workspace / "generated" / "derive_terrain.json"
            write_json(terrain_spec, {"environment": {"overwriteOutput": False}, "operations": [{"id": "derive_terrain", "type": "slope_aspect",
                        "input": dem_source, "slope_output": raw_slope, "aspect_output": raw_aspect,
                        "output_measurement": "DEGREE", "z_unit": "METER"}]})
            terrain_stage = "derive_terrain"
            stages.append({"id": terrain_stage, "adapter": "arcgis", "enabled": True, "spec": str(terrain_spec),
                           "inputs": [dem_source], "outputs": [raw_slope, raw_aspect], "depends_on": dependencies.copy()})
            prepared_drivers.setdefault("slope", raw_slope); prepared_drivers.setdefault("aspect", raw_aspect)
            driver_entries.setdefault("slope", {"path": raw_slope, "type": "continuous", "resampling": "bilinear"})
            driver_entries.setdefault("aspect", {"path": raw_aspect, "type": "circular", "resampling": "nearest"})
        aligned_stages: list[str] = []
        for name, raw in list(prepared_drivers.items()):
            aligned = str(workspace / "outputs" / "drivers" / f"{name}_aligned.tif")
            stage_id = f"align_driver_{name}"
            deps = prepared_dependencies.copy() + ([terrain_stage] if terrain_stage and name in {"slope", "aspect"} else [])
            policy = driver_entries.get(name, {"type": "continuous", "resampling": "bilinear"})
            stages.append({"id": stage_id, "adapter": "command", "enabled": True,
                           "command": [sys.executable, str(ROOT / "scripts" / "raster_grid.py"), "--input", raw,
                                       "--master", master_lulc, "--output", aligned, "--kind", policy["type"],
                                       "--resampling", policy["resampling"]],
                           "inputs": [raw, master_lulc], "outputs": [aligned, aligned + ".metadata.json"], "depends_on": deps})
            prepared_drivers[name] = aligned; aligned_stages.append(stage_id)
        if inputs.get("subsidence_w_dat"):
            source = plus.get("resource_extraction", {}).get("w_dat_preprocessing", {})
            points, depth = str(workspace / "intermediate" / "subsidence_depth_points.csv"), str(workspace / "outputs" / "subsidence" / "subsidence_depth_aligned.tif")
            stages.append({"id": "standardise_w_dat", "adapter": "command", "enabled": True,
                           "command": [sys.executable, str(ROOT / "scripts" / "wdat_to_depth.py"), "--input", source_path(inputs["subsidence_w_dat"], base),
                                       "--output", points, "--unit", str(source.get("source_unit", "m")), "--sign", str(source.get("source_convention", "positive_down"))],
                           "inputs": [source_path(inputs["subsidence_w_dat"], base)], "outputs": [points], "depends_on": prepared_dependencies.copy()})
            wdat = plus.get("resource_extraction", {}).get("w_dat_preprocessing", {})
            scope = source_path(wdat.get("scope_vector") or inputs.get("workface_boundary"), base)
            maximum = wdat.get("max_interpolation_distance_m")
            rasterise_command = [sys.executable, str(ROOT / "scripts" / "wdat_rasterize.py"), "--points", points,
                                 "--master", master_lulc, "--output", depth]
            if wdat.get("interpolation", "nearest_within_scope") != "none":
                rasterise_command += ["--fill-nearest", "--scope-vector", str(scope), "--max-distance-m", str(maximum)]
            stages.append({"id": "rasterise_w_dat", "adapter": "command", "enabled": True,
                           "command": rasterise_command, "inputs": [points, master_lulc] + ([str(scope)] if scope else []),
                           "outputs": [depth, depth + ".metadata.json"], "depends_on": ["standardise_w_dat"]})
            subsidence_depth = depth; aligned_stages.append("rasterise_w_dat")
        elif subsidence_depth:
            depth = str(workspace / "outputs" / "subsidence" / "subsidence_depth_aligned.tif")
            stages.append({"id": "align_subsidence_depth", "adapter": "command", "enabled": True,
                           "command": [sys.executable, str(ROOT / "scripts" / "raster_grid.py"), "--input", subsidence_depth,
                                       "--master", master_lulc, "--output", depth, "--kind", "continuous", "--resampling", "bilinear"],
                           "inputs": [subsidence_depth, master_lulc], "outputs": [depth, depth + ".metadata.json"], "depends_on": prepared_dependencies.copy()})
            subsidence_depth = depth; aligned_stages.append("align_subsidence_depth")
        if plus.get("enabled") and plus_history:
            dataset_entries = [{"name": "master_lulc", "path": master_lulc, "kind": "lulc", "allowed_codes": allowed_codes(classification.get("scheme", "standard_6class")), "must_align": False, "expected_cell_size_m": 30}]
            dataset_entries += [{"name": f"driver_{name}", "path": path,
                                 "kind": "continuous" if driver_entries.get(name, {}).get("type") != "categorical" else "categorical",
                                 "must_align": True, "expected_cell_size_m": 30} for name, path in prepared_drivers.items()]
            if subsidence_depth:
                dataset_entries.append({"name": "subsidence_depth", "path": subsidence_depth, "kind": "subsidence_depth", "must_align": True})
            spec_path, report_path = workspace / "generated" / "plus_input_preflight.json", workspace / "validation" / "plus_input_preflight.json"
            write_json(spec_path, {"master": "master_lulc", "datasets": dataset_entries, "carbon_density": carbon})
            stages.append({"id": "plus_input_preflight", "adapter": "command", "enabled": True,
                           "command": [sys.executable, str(ROOT / "scripts" / "spatial_preflight.py"), "--spec", str(spec_path), "--output", str(report_path)],
                           "inputs": [master_lulc, *prepared_drivers.values()] + ([subsidence_depth] if subsidence_depth else []), "outputs": [str(report_path)],
                           "depends_on": aligned_stages or prepared_dependencies.copy()})
            prepared_dependencies = ["plus_input_preflight"]

    if subsidence.get("enabled") and subsidence.get("mode") == "classify_only":
        evidence = str(workspace / "validation" / "subsidence_water_classification.json")
        stages.append({"id": "subsidence_water_classification_evidence", "adapter": "command", "enabled": True,
                       "command": [sys.executable, str(ROOT / "scripts" / "subsidence_water_evidence.py"), "--lulc", lulc,
                                   "--water-code", str(subsidence.get("water_code", 1)), "--output", evidence],
                       "inputs": [lulc], "outputs": [evidence], "depends_on": lulc_dependency.copy()})

    if subsidence.get("enabled") and subsidence.get("mode") in {"estimate_volume", "composite_subsidence_water_carbon"}:
        mode = subsidence["mode"]
        level = subsidence.get("water_level_elevation_m", inputs.get("water_surface_elevation_m"))
        operation: dict[str, Any] = {"id": "subsidence_water", "type": "subsidence_water_volume" if mode == "estimate_volume" else "subsidence_water_carbon",
            "dem": prepared_drivers.get("dem", source_path(inputs["dem"], base)), "subsidence_depth": subsidence_depth,
            "water_level_elevation_m": level, "water_depth_output": output_path(subsidence["output_depth_raster"], workspace),
            "volume_table": output_path(subsidence["output_volume_table"], workspace)}
        outputs = [operation["water_depth_output"], operation["volume_table"]]
        if mode == "composite_subsidence_water_carbon":
            composite = subsidence["composite_carbon"]
            operation.update({
                "water_boundary": source_path(inputs["subsidence_water_boundary"], base),
                "aquatic_vegetation_output": output_path(subsidence["output_aquatic_vegetation_raster"], workspace),
                "bottom_sediment_output": output_path(subsidence["output_bottom_sediment_raster"], workspace),
                "carbon_table": output_path(subsidence["output_carbon_table"], workspace),
                "water_carbon_density_g_c_m3": composite["water_carbon_density_g_c_m3"],
                "aquatic_vegetation_carbon_density_t_c_ha": composite["aquatic_vegetation_carbon_density_t_c_ha"],
                "bottom_sediment_carbon_density_t_c_ha": composite["bottom_sediment_carbon_density_t_c_ha"],
                "aquatic_vegetation_depth_threshold_m": composite.get("aquatic_vegetation_depth_threshold_m"),
                "bottom_sediment_assume_full_waterbed": composite.get("bottom_sediment_assume_full_waterbed", False),
                "invest_total_carbon_t_c": composite.get("invest_total_carbon_t_c"),
                "invest_subsidence_water_carbon_t_c": composite.get("invest_subsidence_water_carbon_t_c"),
            })
            if inputs.get("aquatic_vegetation_boundary"):
                operation["aquatic_vegetation_mask"] = source_path(inputs["aquatic_vegetation_boundary"], base)
            if inputs.get("bottom_sediment_boundary"):
                operation["bottom_sediment_mask"] = source_path(inputs["bottom_sediment_boundary"], base)
            outputs.extend([operation["aquatic_vegetation_output"], operation["bottom_sediment_output"], operation["carbon_table"]])
        spec_path = workspace / "generated" / "subsidence_water.json"
        write_json(spec_path, {"environment": {"overwriteOutput": False}, "operations": [operation]})
        stages.append({"id": "subsidence_water", "adapter": "arcgis", "enabled": True, "spec": str(spec_path),
                       "inputs": [operation["dem"], operation["subsidence_depth"]], "outputs": outputs,
                       "depends_on": prepared_dependencies.copy()})

    plus_outputs: dict[str, str] = {}
    plus_validation_dependencies: list[str] = []
    if plus.get("enabled"):
        driver_factors = prepared_drivers
        historical = [path for _, path in plus_history]
        plus_root = Path(output_path(plus.get("output_workspace", "outputs/plus"), workspace))
        for raw_scenario in plus.get("scenarios", ["ND", "UD", "EP", "RE"]):
            scenario = str(raw_scenario).upper()
            stage_id, scenario_dir = f"plus_{scenario}", plus_root / scenario
            expected = expected_plus_raster(scenario_dir, scenario)
            parameters: dict[str, Any] = {"historical_lulc": historical, "driver_factors": driver_factors,
                "output_directory": str(scenario_dir), "expected_output": str(expected),
                "plus_settings": {
                    "baseline_year": plus.get("baseline_year"), "target_year": plus.get("target_year"),
                    "random_seed": plus.get("random_seed"), "neighborhood_weights": plus.get("neighborhood_weights"),
                    "transition_matrix": source_path(plus.get("transition_matrix"), base),
                    "constraint_raster": source_path(plus.get("constraint_raster"), base),
                    "land_demand": plus.get("land_demand", {}).get(scenario, plus.get("land_demand", {})),
                }}
            if scenario == "RE":
                parameters["resource_extraction"] = canonical_re_contract(
                    plus["resource_extraction"], subsidence_depth,
                    lambda value: source_path(value, base) or value)
            request = {"protocol_version": "1.0", "request_id": stage_id, "operation": "plus.run_scenario",
                       "parameters": {"project": str(project_path), "scenario": scenario, "workspace": str(scenario_dir),
                                      "parameters": parameters}}
            stage_inputs = [*historical, *driver_factors.values()]
            if scenario == "RE":
                stage_inputs.append(parameters["resource_extraction"]["core_driver_input"])
            stages.append({"id": stage_id, "adapter": "plus", "enabled": True, "request": request,
                           "inputs": stage_inputs, "outputs": [str(expected)], "depends_on": prepared_dependencies.copy()})
            validation_id = lulc_validation_stage(stages, f"plus_output_validation_{scenario}", str(expected), historical[-1],
                                                  classification.get("scheme", "standard_6class"), carbon, workspace, [stage_id])
            add_raster_map(stages, f"PLUS_{scenario}", str(expected), f"PLUS {scenario} scenario", "lulc",
                           classification.get("scheme", "standard_6class"), workspace, [validation_id])
            plus_outputs[scenario] = str(expected)
            plus_validation_dependencies.append(validation_id)

    invest_outputs: dict[str, str] = {}
    invest_service_outputs: dict[str, dict[str, str]] = {}
    invest_dependencies: list[str] = []
    if invest.get("enabled"):
        # Carbon and other InVEST models run for every dated historical LULC,
        # then for every completed PLUS scenario.  Historical products remain
        # available even when PLUS is disabled or paused for GUI handoff.
        historical_sources = {str(year): path for year, path in lulc_history} if len(lulc_history) >= 2 else {}
        if not historical_sources:
            if not lulc:
                raise ValueError("InVEST needs a classified or provided LULC raster")
            historical_sources = {"baseline": lulc}
        lulc_sources = dict(historical_sources)
        dependency_by_scenario = {scenario: lulc_dependency.copy() for scenario in historical_sources}
        for scenario, path in plus_outputs.items():
            lulc_sources[scenario] = path
            dependency_by_scenario[scenario] = [f"plus_output_validation_{scenario}"]
        for model, model_config in enabled_invest_models(invest).items():
            for scenario, source_lulc in lulc_sources.items():
                suffix = "" if scenario == "baseline" else f"_{scenario}"
                stage_id = f"invest_{model}{suffix}"
                datastack = scenario_datastack(model, model_config, source_lulc, carbon, base,
                                               workspace / "generated" / f"{stage_id}_datastack.json")
                model_workspace = Path(output_path(invest.get("output_workspace", "outputs/invest"), workspace)) / model / scenario
                configured_outputs = model_config.get("expected_outputs")
                if configured_outputs is None:
                    configured_outputs = [INVEST_MODELS[model]["default_output"]] if INVEST_MODELS[model]["default_output"] else []
                if not isinstance(configured_outputs, list) or any(not isinstance(item, str) or not item for item in configured_outputs):
                    raise ValueError(f"invest.models.{model}.expected_outputs must be a list of non-empty relative paths")
                outputs = [str((model_workspace / item).resolve()) for item in configured_outputs]
                model_dependencies = dependency_by_scenario[scenario]
                if model != "carbon":
                    contract = str(workspace / "validation" / f"{stage_id}_input_contract.json")
                    contract_id = f"{stage_id}_input_contract"
                    stages.append({"id": contract_id, "adapter": "command", "enabled": True,
                                   "command": [sys.executable, str(ROOT / "scripts" / "invest_ecosystem_contract.py"), "--model", model,
                                               "--datastack", datastack, "--output", contract], "inputs": [datastack],
                                   "outputs": [contract], "depends_on": model_dependencies})
                    model_dependencies = [contract_id]
                stages.append({"id": stage_id, "adapter": "invest", "enabled": True, "model": INVEST_MODELS[model]["cli"],
                               "datastack": datastack, "model_workspace": str(model_workspace),
                               "inputs": [datastack, source_lulc] + ([carbon] if carbon else []),
                               "outputs": outputs, "service_field": str(model_config.get("service_field", INVEST_MODELS[model]["service_field"])),
                               "service_unit": model_config.get("service_unit"),
                               "service_aggregation": model_config.get("service_aggregation", INVEST_MODELS[model].get("service_aggregation", "sum")),
                               "depends_on": model_dependencies})
                for index, result_raster in enumerate(outputs):
                    add_raster_map(stages, f"InVEST_{model}_{scenario}_{index + 1}", result_raster,
                                   f"InVEST {model} {scenario}", "continuous", classification.get("scheme", "standard_6class"),
                                   workspace, [stage_id])
                invest_dependencies.append(stage_id)
                if model == "carbon" and outputs:
                    invest_outputs[scenario] = outputs[0]
                if outputs:
                    service_field = str(model_config.get("service_field", INVEST_MODELS[model]["service_field"]))
                    invest_service_outputs.setdefault(scenario, {})[service_field] = outputs[0]

    ecosystem_dependencies: list[str] = []
    if ecosystem.get("enabled"):
        criteria = source_path(ecosystem.get("criteria_table"), base)
        config = source_path(ecosystem["config"], base)
        if plus_outputs:
            criteria = output_path(ecosystem.get("generated_criteria_table", "outputs/ecosystem/scenario_criteria.csv"), workspace)
            config_payload = read_json(Path(config))
            command = [sys.executable, str(ROOT / "scripts" / "scenario_service_table.py"), "--output", criteria,
                       "--scenario-field", ecosystem.get("analysis", {}).get("scenario_field", "scenario"),
                       "--id-field", config_payload.get("id_field", "unit_id")]
            if ecosystem.get("criteria_table"):
                command.extend(["--supplemental", source_path(ecosystem["criteria_table"], base)])
            grid_cell_pixels = ecosystem.get("analysis", {}).get("grid_cell_pixels")
            if grid_cell_pixels is not None:
                command.extend(["--grid-cell-pixels", str(grid_cell_pixels)])
                geometry = output_path(ecosystem.get("analysis", {}).get("grid_geometry_output", "outputs/ecosystem/scenario_units.geojson"), workspace)
                command.extend(["--grid-geometry", geometry])
            else:
                geometry = None
            for scenario, service_outputs in invest_service_outputs.items():
                if scenario not in plus_outputs:
                    continue
                for field, raster in service_outputs.items():
                    command.extend(["--service-raster", f"{scenario}={field}={raster}"])
            for model, model_config in enabled_invest_models(invest).items():
                field = str(model_config.get("service_field", INVEST_MODELS[model]["service_field"]))
                if model_config.get("service_unit"):
                    command.extend(["--service-unit", f"{field}={model_config['service_unit']}"])
                command.extend(["--service-aggregation", f"{field}={model_config.get('service_aggregation', INVEST_MODELS[model].get('service_aggregation', 'sum'))}"])
            service_inputs = [raster for scenario, services in invest_service_outputs.items() if scenario in plus_outputs
                              for raster in services.values()]
            stages.append({"id": "ecosystem_scenario_inputs", "adapter": "command", "enabled": True, "command": command,
                           "inputs": service_inputs + ([source_path(ecosystem["criteria_table"], base)] if ecosystem.get("criteria_table") else []),
                           "outputs": [item for item in [criteria, criteria + ".metadata.json", geometry] if item], "depends_on": invest_dependencies.copy()})
            ecosystem_dependencies = ["ecosystem_scenario_inputs"]
        else:
            ecosystem_dependencies = invest_dependencies.copy() or lulc_dependency.copy()
        score = output_path(ecosystem.get("output_table", "outputs/ecosystem_service_scores.csv"), workspace)
        stages.append({"id": "ecosystem_service", "adapter": "command", "enabled": True,
            "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_service.py"), "--criteria-table", criteria,
                        "--config", config, "--output", score], "inputs": [criteria, config],
            "outputs": [score, score + ".metadata.json"], "depends_on": ecosystem_dependencies.copy()})
        analysis = ecosystem.get("analysis", {})
        services = analysis.get("tradeoff_fields", [])
        if isinstance(services, list) and len(services) >= 2:
            out = output_path(analysis.get("tradeoff_output", "outputs/ecosystem/tradeoffs.csv"), workspace)
            stages.append({"id": "ecosystem_tradeoffs", "adapter": "command", "enabled": True,
                "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_analysis.py"), "tradeoff", "--table", criteria,
                            "--fields", ",".join(services), "--output", out], "inputs": [criteria], "outputs": [out],
                "depends_on": ["ecosystem_service"]})
        if analysis.get("sensitivity_enabled", True):
            out = output_path(analysis.get("sensitivity_output", "outputs/ecosystem/sensitivity.csv"), workspace)
            stages.append({"id": "ecosystem_sensitivity", "adapter": "command", "enabled": True,
                "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_analysis.py"), "sensitivity", "--table", criteria,
                            "--config", config, "--relative-delta", str(analysis.get("sensitivity_relative_delta", 0.1)), "--output", out],
                "inputs": [criteria, config], "outputs": [out], "depends_on": ["ecosystem_service"]})
        if plus_outputs and analysis.get("reference_scenario", "ND") in plus_outputs:
            out = output_path(analysis.get("scenario_compare_output", "outputs/ecosystem/scenario_comparison.csv"), workspace)
            fields = analysis.get("scenario_value_fields", ["ecosystem_service_score"])
            stages.append({"id": "ecosystem_scenario_comparison", "adapter": "command", "enabled": True,
                "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_analysis.py"), "compare", "--table", score,
                            "--reference", analysis.get("reference_scenario", "ND"), "--scenario-field", analysis.get("scenario_field", "scenario"),
                            "--id-field", analysis.get("id_field", read_json(Path(config)).get("id_field", "unit_id")),
                            "--fields", ",".join(fields), "--output", out], "inputs": [score], "outputs": [out],
                "depends_on": ["ecosystem_service"]})
        geo_fields = analysis.get("geodetector_factor_fields", [])
        geo_table = source_path(analysis.get("geodetector_samples"), base)
        geodetector_dependencies = ["ecosystem_service"]
        if geo_fields and not geo_table and analysis.get("geodetector_target_raster") and analysis.get("geodetector_factor_rasters"):
            geo_table = output_path(analysis.get("geodetector_samples_output", "outputs/ecosystem/geodetector_samples.csv"), workspace)
            target_raster = source_path(analysis["geodetector_target_raster"], base)
            sample_command = [sys.executable, str(ROOT / "scripts" / "geodetector_spatial_samples.py"), "--target", target_raster,
                              "--target-field", analysis.get("geodetector_target_field", "ecosystem_service_score"), "--output", geo_table,
                              "--sample-step", str(analysis.get("geodetector_sample_step", 1)),
                              "--continuous-bins", str(analysis.get("geodetector_continuous_bins", 6))]
            sample_inputs = [target_raster]
            for name in geo_fields:
                raster = source_path(analysis["geodetector_factor_rasters"].get(name), base)
                sample_command.extend(["--factor", f"{name}={raster}"]); sample_inputs.append(raster)
            stages.append({"id": "ecosystem_geodetector_samples", "adapter": "command", "enabled": True,
                           "command": sample_command, "inputs": sample_inputs, "outputs": [geo_table, geo_table + ".metadata.json"],
                           "depends_on": ["ecosystem_service"]})
            geodetector_dependencies = ["ecosystem_geodetector_samples"]
        if geo_fields and geo_table:
            out = output_path(analysis.get("geodetector_output", "outputs/ecosystem/geodetector.csv"), workspace)
            stages.append({"id": "ecosystem_geodetector", "adapter": "command", "enabled": True,
                "command": [sys.executable, str(ROOT / "scripts" / "ecosystem_analysis.py"), "geodetector", "--table", geo_table,
                            "--target", analysis.get("geodetector_target_field", "ecosystem_service_score"), "--fields", ",".join(geo_fields), "--output", out],
                "inputs": [geo_table], "outputs": [out], "depends_on": geodetector_dependencies})

    completed = [stage["id"] for stage in stages if stage.get("enabled")]
    if gis_outputs.get("enabled"):
        map_layers = [map_layer_definition(item, base) for item in gis_outputs.get("layers", [])]
        map_validation = str(workspace / "validation" / "map_layout.json")
        map_aprx = output_path(gis_outputs.get("aprx_output", "outputs/maps/composed_project.aprx"), workspace)
        map_outputs = [map_aprx, map_validation]
        if gis_outputs.get("pdf"):
            map_outputs.append(output_path(gis_outputs["pdf"], workspace))
        if gis_outputs.get("png"):
            map_outputs.append(output_path(gis_outputs["png"], workspace))
        map_inputs = [source_path(gis_outputs["aprx"], base)]
        for layer in map_layers:
            map_inputs.append(layer["path"])
            if layer.get("symbology_layer"):
                map_inputs.append(layer["symbology_layer"])
        spec = {"environment": {"overwriteOutput": False}, "operations": [{"id": "compose_final_layout", "type": "compose_layout",
            "aprx": source_path(gis_outputs["aprx"], base), "layout_name": gis_outputs["layout_name"], "map_name": gis_outputs.get("map_name"),
            "map_frame_name": gis_outputs.get("map_frame_name"), "title_element_name": gis_outputs.get("title_element_name"),
            "extent_from_layer": gis_outputs.get("extent_from_layer"), "aprx_output": map_aprx,
            "layers": map_layers, "title_text": gis_outputs.get("title_text"), "legend_name": gis_outputs.get("legend_name"),
            "pdf": output_path(gis_outputs["pdf"], workspace) if gis_outputs.get("pdf") else None,
            "png": output_path(gis_outputs["png"], workspace) if gis_outputs.get("png") else None, "resolution": gis_outputs.get("resolution", 300),
            "validation_output": map_validation}]}
        spec_path = workspace / "generated" / "compose_layout.json"; write_json(spec_path, spec)
        stages.append({"id": "map_layout", "adapter": "arcgis", "enabled": True, "spec": str(spec_path),
                       "inputs": map_inputs, "outputs": map_outputs,
                       "depends_on": completed.copy()})
        completed.append("map_layout")
    if validation_config.get("enabled"):
        inferred_sections = [name for name, enabled in (("lulc", classification.get("enabled")), ("plus", plus.get("enabled")),
                             ("invest", invest.get("enabled")), ("ecosystem", ecosystem.get("enabled")),
                             ("subsidence_water", subsidence.get("enabled")),
                             ("map", gis_outputs.get("enabled"))) if enabled]
        required_sections = validation_config.get("required_sections", inferred_sections)
        evidence = source_path(validation_config.get("evidence_file"), base)
        if evidence:
            evidence_dependencies, evidence_inputs = completed.copy(), [evidence]
        else:
            evidence = str(workspace / "validation" / "analysis_evidence.json")
            stages.append({"id": "assemble_validation_evidence", "adapter": "command", "enabled": True,
                           "command": [sys.executable, str(ROOT / "scripts" / "assemble_validation_evidence.py"), "--workspace", str(workspace),
                                       "--required-sections", ",".join(required_sections), "--output", evidence],
                           "inputs": [], "outputs": [evidence], "depends_on": completed.copy()})
            evidence_dependencies, evidence_inputs = ["assemble_validation_evidence"], []
        output = output_path(validation_config["output_report"], workspace)
        stages.append({"id": "analysis_validation", "adapter": "command", "enabled": True,
                       "command": [sys.executable, str(ROOT / "scripts" / "analysis_validation.py"), "--validation-file", evidence,
                                   "--output-report", output], "inputs": [evidence, *evidence_inputs], "outputs": [output], "depends_on": evidence_dependencies})
    job = {"schema_version": 1, "project_id": project["project_id"], "workspace": str(workspace), "project_file": str(project_path),
           "security": {"input_roots": [str(resolved(item, base)) for item in project.get("security", {}).get("input_roots", ["."])],
                        "output_root": str(workspace), "confirm_overwrite": bool(project.get("security", {}).get("confirm_overwrite", False))},
           "software": project.get("software", {}), "stages": stages}
    write_json(output_job, job)
    return {"project_id": project["project_id"], "workspace": str(workspace), "workflow_job": str(output_job),
            "stage_ids": [stage["id"] for stage in stages], "warnings": report["warnings"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path); parser.add_argument("--output-job", type=Path)
    parser.add_argument("--run", action="store_true"); parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true"); parser.add_argument("--confirm-overwrite", action="store_true")
    args = parser.parse_args(); report = compile_workflow(args.project, args.output_job)
    if not args.run:
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 0
    from workflow_agent import JobRunner
    runner = JobRunner(Path(report["workflow_job"]), args.dry_run, args.continue_on_error, args.confirm_overwrite)
    code = runner.run(); report.update({"agent_state": str(runner.state_path), "return_code": code})
    print(json.dumps(report, ensure_ascii=False, indent=2)); return code


if __name__ == "__main__":
    raise SystemExit(main())
