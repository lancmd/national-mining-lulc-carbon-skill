#!/usr/bin/env python3
"""Local command backend for local-project validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_validator import validate  # noqa: E402
from project_builder import build as build_project  # noqa: E402
from project_workflow import compile_workflow  # noqa: E402
from analysis_validation import validate_results  # noqa: E402
from lulc_accuracy import evaluate as evaluate_lulc  # noqa: E402
from workflow_agent import JobRunner  # noqa: E402
from prepare_plus_scenarios import prepare as prepare_plus_scenarios  # noqa: E402
from job_manager import cancel as cancel_job, outputs as job_outputs, status as job_status, submit as submit_job  # noqa: E402


def main() -> int:
    envelope = json.load(sys.stdin)
    if envelope.get("operation") == "system.capabilities":
        result = {"status": "completed", "result": {"backend": "project", "mode": "local-command", "operations": [
            "system.capabilities", "project.build_from_inputs", "project.validate", "project.compile_workflow", "project.run_workflow",
            "project.prepare_plus_scenarios", "project.submit_workflow", "system.job_status", "system.cancel_job", "system.list_outputs",
            "analysis.validate_results", "analysis.lulc_accuracy", "analysis.plus_validation", "analysis.invest_consistency",
        ]}}
    elif envelope.get("operation") == "project.build_from_inputs":
        params = envelope["parameters"]
        report = build_project(Path(params["output_project"]), params["project_id"], params["workspace"],
                               params.get("imagery_periods"), params.get("driver_factors"), params.get("mine_boundary"),
                               params.get("carbon_density"), task_type=params.get("task_type", "full_chain"),
                               historical_lulc_periods=params.get("historical_lulc_periods"),
                               ecosystem_criteria=params.get("ecosystem_criteria"), ecosystem_config=params.get("ecosystem_config"),
                               gis_outputs=params.get("gis_outputs"), w_dat=params.get("w_dat"), model_package=params.get("model_package"),
                               training_roi=params.get("training_roi"), scheme=params.get("scheme", "high_water_coal_7class"),
                               w_dat_unit=params.get("w_dat_unit"), w_dat_convention=params.get("w_dat_convention"),
                               workface_boundary=params.get("workface_boundary"),
                               w_dat_max_distance_m=params.get("w_dat_max_distance_m", 300.0),
                               subsidence_depth_raster=params.get("subsidence_depth_raster"),
                               patch_size=params.get("patch_size"), patch_stride=params.get("patch_stride"),
                               patch_band_indexes=params.get("patch_band_indexes"), patch_input_scale=params.get("patch_input_scale"),
                               patch_batch_size=params.get("patch_batch_size"),
                               allow_patch_grid_as_lulc=bool(params.get("allow_patch_grid_as_lulc", False)),
                               invest_models=params.get("invest_models"))
        # Building a project is not evidence that its local files and model
        # contracts are runnable.  Always validate the generated document in
        # the same request so callers receive one authoritative status.
        validation = validate(Path(report["project_file"]))
        report["project_validation"] = validation
        if validation["status"] != "valid":
            status = "failed"
            error = "; ".join(validation["errors"])
        elif report["pending_inputs"]:
            status, error = "pending_validation", None
        else:
            status, error = "completed", None
        result = {"status": status, "result": report, "outputs": [report["project_file"]], "error": error}
    elif envelope.get("operation") == "project.validate":
        report = validate(Path(envelope["parameters"]["project_file"]).expanduser().resolve())
        result = {"status": "completed" if report["status"] == "valid" else "failed", "result": report,
                  "error": None if report["status"] == "valid" else "; ".join(report["errors"])}
    elif envelope.get("operation") == "project.compile_workflow":
        params = envelope["parameters"]
        output = params.get("output_job")
        report = compile_workflow(Path(params["project_file"]), Path(output) if output else None)
        result = {"status": "completed", "result": report, "outputs": [report["workflow_job"]]}
    elif envelope.get("operation") == "project.run_workflow":
        params = envelope["parameters"]
        output = params.get("output_job")
        compiled = compile_workflow(Path(params["project_file"]), Path(output) if output else None)
        runner = JobRunner(Path(compiled["workflow_job"]), bool(params.get("dry_run")),
                           bool(params.get("continue_on_error")), bool(params.get("confirm_overwrite")))
        return_code = runner.run()
        state = json.loads(runner.state_path.read_text(encoding="utf-8")) if runner.state_path.exists() else {"stages": {}}
        statuses = {item.get("status") for item in state.get("stages", {}).values()}
        status = "failed" if return_code else "waiting_interactive" if "waiting_interactive" in statuses else "prepared" if "prepared" in statuses else "pending_validation" if "pending_validation" in statuses else "completed"
        result = {"status": status, "result": {"compiled": compiled, "state": str(runner.state_path), "stage_statuses": state.get("stages", {})},
                  "outputs": [compiled["workflow_job"], str(runner.state_path)]}
    elif envelope.get("operation") == "project.prepare_plus_scenarios":
        params = envelope["parameters"]
        output = params.get("output_job")
        report = prepare_plus_scenarios(Path(params["project_file"]), Path(output) if output else None)
        result = {"status": "completed", "result": report, "outputs": [report["workflow_job"], report["manifest"]]}
    elif envelope.get("operation") == "project.submit_workflow":
        params = envelope["parameters"]
        output = params.get("output_job")
        compiled = compile_workflow(Path(params["project_file"]), Path(output) if output else None)
        record = submit_job(Path(compiled["workflow_job"]), bool(params.get("dry_run")), bool(params.get("continue_on_error")),
                            bool(params.get("confirm_overwrite")))
        result = {"status": "accepted", "result": record, "outputs": [record["log"]]}
    elif envelope.get("operation") == "system.job_status":
        result = {"status": "completed", "result": job_status(envelope["parameters"]["job_id"])}
    elif envelope.get("operation") == "system.cancel_job":
        result = {"status": "cancelled", "result": cancel_job(envelope["parameters"]["job_id"])}
    elif envelope.get("operation") == "system.list_outputs":
        result = {"status": "completed", "result": job_outputs(envelope["parameters"]["job_id"])}
    elif envelope.get("operation") == "analysis.validate_results":
        params = envelope["parameters"]
        output = params.get("output_report")
        report = validate_results(Path(params["validation_file"]), Path(output) if output else None)
        result = {"status": report["status"], "result": report, "outputs": [report["output"]]}
    elif envelope.get("operation") == "analysis.lulc_accuracy":
        params = envelope["parameters"]
        report = evaluate_lulc(Path(params["samples_file"]), params.get("reference_field", "reference"),
                               params.get("prediction_field", "prediction"), Path(params["output"]))
        result = {"status": "completed", "result": report, "outputs": [report["output"]]}
    elif envelope.get("operation") == "analysis.plus_validation":
        params = envelope["parameters"]
        from plus_validation import evaluate as evaluate_plus
        report = evaluate_plus(Path(params["reference_raster"]), Path(params["predicted_raster"]),
                               Path(params["baseline_raster"]), params.get("seed_predictions", []), Path(params["output"]))
        status = "completed" if len(report.get("seed_metrics", [])) >= 2 else "pending_validation"
        result = {"status": status, "result": report, "outputs": [report["output"]]}
    elif envelope.get("operation") == "analysis.invest_consistency":
        params = envelope["parameters"]
        from invest_consistency import compare
        report = compare(Path(params["workflow_raster"]), Path(params["independent_raster"]),
                         float(params.get("relative_tolerance", 0.001)), Path(params["output"]))
        result = {"status": report["status"], "result": report, "outputs": [report["output"]]}
    else:
        result = {"status": "failed", "error": "unsupported project operation"}
    result.update({"protocol_version": "1.0", "request_id": envelope.get("request_id")})
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
