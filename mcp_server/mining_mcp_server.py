#!/usr/bin/env python3
"""Local-first MCP server for mining-area GIS operations."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib import request
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from plus_contract import re_contract_errors  # noqa: E402
from path_safety import PathSafetyError, is_unc, require_within  # noqa: E402
DEFAULT_REGISTRY = ROOT / "interfaces" / "backend_registry.json"
EXAMPLE_REGISTRY = ROOT / "interfaces" / "backend_registry.example.json"
VALID_PLUS_SCENARIOS = frozenset({"ND", "UD", "EP", "RE"})
INPUT_PATH_KEYS = {"path", "project_file", "project", "datastack", "model_package", "input_raster", "training_vector",
                   "criteria_table", "config", "samples_file", "reference_raster", "predicted_raster", "baseline_raster",
                   "workflow_raster", "independent_raster", "scores_table", "candidates_table", "sample_table", "samples_table",
                   "validation_file", "input", "inputs", "aprx", "symbology_layer", "dem", "subsidence_depth",
                   "water_boundary", "core_driver_input", "carbon_pools_path", "imagery", "historical_lulc", "lulc_baseline",
                   "driver_factors", "mine_boundary", "roi", "training_roi", "subsidence_water_boundary",
                   "carbon_density", "subsidence_depth_raster", "w_dat", "workface_boundary"}
OUTPUT_PATH_KEYS = {"output", "output_job", "workspace", "class_output", "confidence_output", "low_confidence_output",
                    "output_raster", "output_report", "expected_output", "output_directory", "water_depth_output",
                    "volume_table", "carbon_table", "pdf", "png", "aprx_output", "validation_output", "model_workspace", "output_project"}


def allowed_input_roots() -> list[Path]:
    raw = os.getenv("MINING_GIS_INPUT_ROOTS")
    values = raw.split(os.pathsep) if raw else [str(ROOT)]
    roots = [Path(value).expanduser().resolve() for value in values if value]
    if not roots or any(is_unc(str(root)) for root in roots):
        raise PathSafetyError("MINING_GIS_INPUT_ROOTS must contain one or more local directories")
    return roots


def allowed_output_root() -> Path:
    value = os.getenv("MINING_GIS_OUTPUT_ROOT", str(ROOT / "outputs"))
    if is_unc(value):
        raise PathSafetyError("MINING_GIS_OUTPUT_ROOT cannot be a UNC/network path")
    return Path(value).expanduser().resolve()


def _path_role(key: str | None, inherited: str | None) -> str | None:
    if key in OUTPUT_PATH_KEYS:
        return "output"
    if key in INPUT_PATH_KEYS:
        return "input"
    normalized = (key or "").lower()
    if normalized.startswith("output_") or normalized.endswith(("_output", "_output_path", "_output_file")):
        return "output"
    if any(token in normalized for token in ("path", "file", "raster", "vector", "imagery", "lulc", "boundary", "roi", "datastack", "table", "workspace", "directory")):
        return inherited or "input"
    return inherited


def guard_paths(value: Any, key: str | None = None, inherited: str | None = None) -> None:
    """Apply one local root policy to direct MCP invocations and nested specs."""
    role = _path_role(key, inherited)
    if isinstance(value, dict):
        for nested_key, nested_value in value.items():
            guard_paths(nested_value, str(nested_key), role)
        return
    if isinstance(value, list):
        for item in value:
            guard_paths(item, key, role)
        return
    if not isinstance(value, str) or not value or role is None:
        return
    if is_unc(value):
        raise PathSafetyError(f"{key} cannot use a UNC/network path")
    candidate = Path(os.path.expandvars(value)).expanduser()
    if ".." in candidate.parts:
        raise PathSafetyError(f"{key} cannot use parent-directory traversal")
    path = candidate.resolve()
    if role == "input":
        require_within(path, allowed_input_roots(), f"MCP input {key}")
    else:
        require_within(path, [allowed_output_root()], f"MCP output {key}")


def is_loopback_host(host: str | None) -> bool:
    """Accept only local endpoints; MCP is a local process protocol in this project."""
    if not host:
        return False
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def require_local_transport(config: dict[str, Any]) -> None:
    transport = config.get("transport")
    if transport == "socket" and not is_loopback_host(str(config.get("host", "127.0.0.1"))):
        raise ValueError("socket backend must use a loopback host; remote software control is disabled")
    if transport == "http":
        parsed = urlparse(str(config.get("url", "")))
        if parsed.scheme != "http" or not is_loopback_host(parsed.hostname):
            raise ValueError("HTTP backend must use a loopback http:// endpoint; remote software control is disabled")


def json_result(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


class BackendRegistry:
    def __init__(self, path: str | None = None):
        configured = path or os.getenv("MINING_GIS_BACKENDS")
        self.path = Path(configured).expanduser().resolve() if configured else DEFAULT_REGISTRY
        source = self.path if self.path.exists() else EXAMPLE_REGISTRY
        with source.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
        self.protocol_version = str(payload.get("protocol_version", "1.0"))
        self.backends: dict[str, dict[str, Any]] = payload.get("backends", {})

    def public_summary(self) -> dict[str, Any]:
        result = {}
        for name, config in self.backends.items():
            result[name] = {
                "transport": config.get("transport"),
                "capabilities": config.get("capabilities", []),
                "configured": self.path.exists(),
            }
        return {"protocol_version": self.protocol_version, "registry": str(self.path), "backends": result}

    def call(self, backend: str, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if backend not in self.backends:
            return {"status": "failed", "error": f"backend is not registered: {backend}"}
        config = self.backends[backend]
        advertised = config.get("capabilities", [])
        if advertised and operation not in advertised and operation != "system.capabilities":
            return {"status": "failed", "error": f"backend {backend} does not advertise {operation}"}
        envelope = {
            "protocol_version": self.protocol_version,
            "request_id": str(uuid.uuid4()),
            "operation": operation,
            "parameters": parameters,
        }
        try:
            guard_paths(parameters)
            require_local_transport(config)
            transport = config.get("transport")
            if transport == "http":
                return self._http(config, envelope)
            if transport == "socket":
                return self._socket(config, envelope)
            if transport == "command":
                return self._command(config, envelope)
            return {**envelope, "status": "failed", "error": f"unsupported transport: {transport}"}
        except Exception as error:
            return {**envelope, "status": "failed", "error": str(error)}

    @staticmethod
    def _http(config: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        req = request.Request(config["url"], data=json.dumps(envelope).encode("utf-8"), headers=headers, method="POST")
        with request.urlopen(req, timeout=float(config.get("timeout", 600))) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _socket(config: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
        timeout = float(config.get("timeout", 600))
        with socket.create_connection((config.get("host", "127.0.0.1"), int(config["port"])), timeout=timeout) as client:
            client.settimeout(timeout)
            client.sendall(json.dumps(envelope, ensure_ascii=False).encode("utf-8") + b"\n")
            chunks = bytearray()
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.extend(chunk)
                try:
                    return json.loads(chunks.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
        raise RuntimeError("backend socket closed without a JSON response")

    @staticmethod
    def _command(config: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
        command = config.get("command")
        if not isinstance(command, list) or not command:
            raise ValueError("command transport requires a non-empty command array")
        command = [os.path.expandvars(str(item)).replace("{python}", sys.executable)
                   .replace("{skill_root}", str(ROOT)) for item in command]
        # ASCII-escaped JSON avoids surrogate/path corruption across Windows process boundaries.
        process = subprocess.run(command, input=json.dumps(envelope, ensure_ascii=True), text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                 errors="replace", timeout=float(config.get("timeout", 600)), check=False)
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or f"backend returned {process.returncode}")
        return json.loads(process.stdout)


registry = BackendRegistry()
mcp = FastMCP(
    "mining-gis",
    instructions=(
        "Execute mining-area GIS tasks through local software backends only. "
        "Use structured tools and distinguish completed results from prepared task packages."
    ),
)


@mcp.tool()
def list_backends() -> str:
    """List registered GIS software backends, transports, and advertised capabilities."""
    return json_result(registry.public_summary())


@mcp.tool()
def backend_capabilities(backend: str) -> str:
    """Query a backend for its live software version, operations, limits, and authentication state."""
    return json_result(registry.call(backend, "system.capabilities", {}))


@mcp.tool()
def inspect_dataset(path: str, backend: str = "arcgis") -> str:
    """Inspect CRS, extent, resolution, shape, NoData, bands, pixel type, and value information for a spatial dataset."""
    return json_result(registry.call(backend, "dataset.inspect", {"path": path}))


@mcp.tool()
def validate_local_project(project_file: str, backend: str = "project") -> str:
    """Validate all local imagery, ROI, carbon-density, driver-factor and optional subsidence inputs before execution."""
    return json_result(registry.call(backend, "project.validate", {"project_file": project_file}))


@mcp.tool()
def build_local_project_from_inputs(output_project: str, project_id: str, workspace: str,
                                    imagery_periods: list[dict[str, Any]], driver_factors: dict[str, Any],
                                    mine_boundary: str, carbon_density: str, w_dat: str | None = None,
                                    model_package: str | None = None, training_roi: str | None = None,
                                    scheme: str = "high_water_coal_7class", w_dat_unit: str | None = None,
                                    w_dat_convention: str | None = None, workface_boundary: str | None = None,
                                    w_dat_max_distance_m: float = 300.0, subsidence_depth_raster: str | None = None,
                                    backend: str = "project") -> str:
    """Build a local multi-date project from supplied paths.

    Supply carbon_density.  For RE/subsidence use either a standardised
    subsidence_depth_raster (the user-made settlement cloud) or w_dat with its
    unit, sign convention and bounded interpolation scope; not both.
    """
    return json_result(registry.call(backend, "project.build_from_inputs", {
        "output_project": output_project, "project_id": project_id, "workspace": workspace,
        "imagery_periods": imagery_periods, "driver_factors": driver_factors, "mine_boundary": mine_boundary,
        "carbon_density": carbon_density, "w_dat": w_dat, "model_package": model_package, "training_roi": training_roi,
        "scheme": scheme, "w_dat_unit": w_dat_unit, "w_dat_convention": w_dat_convention,
        "workface_boundary": workface_boundary, "w_dat_max_distance_m": w_dat_max_distance_m,
        "subsidence_depth_raster": subsidence_depth_raster,
    }))


@mcp.tool()
def compile_project_workflow(project_file: str, output_job: str | None = None, backend: str = "project") -> str:
    """Validate a local project and compile it into an executable workflow job; no manual workflow_job editing is needed."""
    return json_result(registry.call(backend, "project.compile_workflow", {
        "project_file": project_file, "output_job": output_job,
    }))


@mcp.tool()
def prepare_all_plus_scenarios(project_file: str, output_job: str | None = None, backend: str = "project") -> str:
    """Create ND/UD/EP/RE request packs and GUI checklists without opening multiple PLUS windows."""
    return json_result(registry.call(backend, "project.prepare_plus_scenarios", {
        "project_file": project_file, "output_job": output_job,
    }))


@mcp.tool()
def run_local_project(project_file: str, output_job: str | None = None, dry_run: bool = False,
                      continue_on_error: bool = False, confirm_overwrite: bool = False, backend: str = "project") -> str:
    """Compile and run the locally available stages from one project configuration, preserving logs and stage state."""
    return json_result(registry.call(backend, "project.run_workflow", {
        "project_file": project_file, "output_job": output_job, "dry_run": dry_run,
        "continue_on_error": continue_on_error, "confirm_overwrite": confirm_overwrite,
    }))


@mcp.tool()
def submit_local_project(project_file: str, output_job: str | None = None, dry_run: bool = False,
                         continue_on_error: bool = False, confirm_overwrite: bool = False, backend: str = "project") -> str:
    """Submit a local workflow to the background job registry and return immediately with a job ID."""
    return json_result(registry.call(backend, "project.submit_workflow", {
        "project_file": project_file, "output_job": output_job, "dry_run": dry_run,
        "continue_on_error": continue_on_error, "confirm_overwrite": confirm_overwrite,
    }))


@mcp.tool()
def resume_job(project_file: str, output_job: str | None = None, continue_on_error: bool = False,
               confirm_overwrite: bool = False, backend: str = "project") -> str:
    """Resume a locally compiled workflow from its persisted agent state in the background."""
    return submit_local_project(project_file, output_job, False, continue_on_error, confirm_overwrite, backend)


@mcp.tool()
def validate_analysis_results(validation_file: str, output_report: str | None = None,
                              backend: str = "project") -> str:
    """Check LULC, PLUS, InVEST, ecosystem-service, and map-quality evidence rather than only task completion."""
    return json_result(registry.call(backend, "analysis.validate_results", {
        "validation_file": validation_file, "output_report": output_report,
    }))


@mcp.tool()
def evaluate_lulc_accuracy(samples_file: str, output: str, reference_field: str = "reference",
                           prediction_field: str = "prediction", backend: str = "project") -> str:
    """Calculate OA, macro F1/IoU, and per-class precision, recall, F1, and IoU from validation samples."""
    return json_result(registry.call(backend, "analysis.lulc_accuracy", {
        "samples_file": samples_file, "reference_field": reference_field,
        "prediction_field": prediction_field, "output": output,
    }))


@mcp.tool()
def validate_plus_backcast(reference_raster: str, predicted_raster: str, baseline_raster: str,
                           output: str, seed_predictions: list[dict[str, Any]] | None = None,
                           backend: str = "project") -> str:
    """Calculate PLUS FoM, land-class accuracy, and FoM stability across supplied random-seed rasters."""
    return json_result(registry.call(backend, "analysis.plus_validation", {
        "reference_raster": reference_raster, "predicted_raster": predicted_raster,
        "baseline_raster": baseline_raster, "seed_predictions": seed_predictions or [], "output": output,
    }))


@mcp.tool()
def validate_invest_consistency(workflow_raster: str, independent_raster: str, output: str,
                                relative_tolerance: float = 0.001, backend: str = "project") -> str:
    """Compare workflow and independently executed InVEST Carbon rasters on the same grid."""
    return json_result(registry.call(backend, "analysis.invest_consistency", {
        "workflow_raster": workflow_raster, "independent_raster": independent_raster,
        "relative_tolerance": relative_tolerance, "output": output,
    }))


@mcp.tool()
def run_envi_classification(input_raster: str, training_vector: str, output_raster: str,
                            method: str = "maximum_likelihood", backend: str = "envi") -> str:
    """Run ENVI supervised classification. Method is maximum_likelihood or minimum_distance."""
    if method not in {"maximum_likelihood", "minimum_distance"}:
        return json_result({"status": "failed", "error": f"unsupported ENVI method: {method}"})
    return json_result(registry.call(backend, "envi.supervised_classification", {
        "input_raster": input_raster, "training_vector": training_vector,
        "output_raster": output_raster, "method": method
    }))


@mcp.tool()
def run_arcgis_operations(spec: dict[str, Any], workspace: str, confirm_overwrite: bool = False,
                          backend: str = "arcgis") -> str:
    """Run declarative ArcGIS raster/vector operations using a software bridge rather than an installation path."""
    return json_result(registry.call(backend, "arcgis.run_operations", {
        "spec": spec, "workspace": workspace, "confirm_overwrite": confirm_overwrite,
    }))


@mcp.tool()
def calibrate_plus_v142(workspace: str, process_id: int | None = None, open_menu: str | None = None,
                         open_menu_item: str | None = None,
                         close_auxiliary_dialogs: bool = False,
                         backend: str = "plus") -> str:
    """Open local official PLUS V1.4.2 once and save a local UI-control calibration report; it does not submit a model run."""
    parameters: dict[str, Any] = {"workspace": workspace}
    if process_id is not None:
        parameters["process_id"] = process_id
    if open_menu is not None:
        parameters["open_menu"] = open_menu
    if open_menu_item is not None:
        parameters["open_menu_item"] = open_menu_item
    if close_auxiliary_dialogs:
        parameters["close_auxiliary_dialogs"] = True
    return json_result(registry.call(backend, "plus.calibrate", parameters))


@mcp.tool()
def run_plus_scenario(project: str, scenario: str, workspace: str,
                      parameters: dict[str, Any] | None = None, backend: str = "plus") -> str:
    """Run ND, UD, EP, or RE through PLUS. RE requires an aligned positive subsidence-depth TIFF plus other drivers."""
    scenario_code = scenario.strip().upper()
    if scenario_code not in VALID_PLUS_SCENARIOS:
        return json_result({"status": "failed", "error": f"PLUS scenario must be one of {sorted(VALID_PLUS_SCENARIOS)}"})
    scenario_parameters = parameters or {}
    if scenario_code == "RE":
        resource = scenario_parameters.get("resource_extraction")
        errors = re_contract_errors(resource)
        if errors:
            return json_result({"status": "failed", "error": "; ".join(errors)})
        driver = Path(resource["core_driver_input"]).expanduser()
        value = str(driver)
        if not driver.is_file() or is_unc(value):
            return json_result({"status": "failed", "error": f"RE core_driver_input is not a local TIFF file: {value}"})
    return json_result(registry.call(backend, "plus.run_scenario", {
        "project": project, "scenario": scenario_code, "workspace": workspace, "parameters": scenario_parameters
    }))


@mcp.tool()
def run_invest_carbon(datastack: str, workspace: str, backend: str = "invest") -> str:
    """Run InVEST Carbon from a parameter-set/datastack through a registered backend."""
    return json_result(registry.call(backend, "invest.run_carbon", {"datastack": datastack, "workspace": workspace}))


@mcp.tool()
def run_invest_ecosystem_model(model: str, datastack: str, workspace: str, backend: str = "invest") -> str:
    """Run a local InVEST ecosystem-service model using a current-version datastack."""
    if model not in {"annual_water_yield", "habitat_quality", "carbon", "sdr", "ndr"}:
        return json_result({"status": "failed", "error": "model must be annual_water_yield, habitat_quality, carbon, sdr, or ndr"})
    return json_result(registry.call(backend, "invest.run_model", {
        "model": model, "datastack": datastack, "workspace": workspace
    }))


@mcp.tool()
def validate_lulc_model(model_package: str, backend: str = "pytorch") -> str:
    """Validate a portable PyTorch LULC model package, class map, preprocessing contract, and weights hash."""
    return json_result(registry.call(backend, "pytorch.validate_model", {"model_package": model_package}))


@mcp.tool()
def run_pytorch_lulc(model_package: str, input_raster: str, class_output: str,
                     confidence_output: str, device: str = "auto", low_confidence_output: str | None = None,
                     low_confidence_threshold: float | None = None, backend: str = "pytorch") -> str:
    """Run tiled PyTorch LULC inference and create classification and confidence GeoTIFF outputs."""
    return json_result(registry.call(backend, "pytorch.run_lulc_inference", {
        "model_package": model_package, "input_raster": input_raster,
        "class_output": class_output, "confidence_output": confidence_output, "device": device,
        "low_confidence_output": low_confidence_output, "low_confidence_threshold": low_confidence_threshold,
    }))


@mcp.tool()
def evaluate_ecosystem_services(criteria_table: str, config: str, output: str,
                                backend: str = "ecosystem") -> str:
    """Fuse carbon, annual water yield, habitat quality, or other user-supplied services with Min-Max or AHP."""
    return json_result(registry.call(backend, "ecosystem.evaluate", {
        "criteria_table": criteria_table, "config": config, "output": output
    }))


@mcp.tool()
def analyze_ecosystem_tradeoffs(criteria_table: str, fields: list[str], output: str,
                                backend: str = "ecosystem") -> str:
    """Calculate pairwise Spearman synergy/trade-off relationships without inferring statistical significance."""
    return json_result(registry.call(backend, "ecosystem.tradeoff_analysis", {
        "criteria_table": criteria_table, "fields": fields, "output": output
    }))


@mcp.tool()
def compare_ecosystem_scenarios(scores_table: str, reference_scenario: str, output: str,
                                scenario_field: str = "scenario", value_fields: list[str] | None = None,
                                backend: str = "ecosystem") -> str:
    """Compare normalized ecosystem-service scores across ND, UD, EP, RE, or user-defined scenarios."""
    return json_result(registry.call(backend, "ecosystem.scenario_compare", {
        "scores_table": scores_table, "reference_scenario": reference_scenario, "scenario_field": scenario_field,
        "value_fields": value_fields or ["ecosystem_service_score"], "output": output
    }))


@mcp.tool()
def calibrate_annual_water_yield(candidates_table: str, observed_volume_m3: float, output: str,
                                 parameter_field: str = "seasonality_constant_z",
                                 modeled_volume_field: str = "modeled_water_yield_m3",
                                 backend: str = "ecosystem") -> str:
    """Select the InVEST annual-water-yield parameter candidate with the smallest compatible-volume error."""
    return json_result(registry.call(backend, "ecosystem.water_yield_calibration", {
        "candidates_table": candidates_table, "observed_volume_m3": observed_volume_m3,
        "parameter_field": parameter_field, "modeled_volume_field": modeled_volume_field, "output": output
    }))


@mcp.tool()
def analyze_ecosystem_drivers(samples_table: str, target_field: str, factor_fields: list[str], output: str,
                              backend: str = "ecosystem") -> str:
    """Run GeoDetector q and interaction analysis on pre-classified factor strata and service-score samples."""
    return json_result(registry.call(backend, "ecosystem.geodetector_factor_analysis", {
        "samples_table": samples_table, "target_field": target_field, "factor_fields": factor_fields, "output": output
    }))


@mcp.tool()
def analyze_ecosystem_sensitivity(criteria_table: str, config: str, output: str,
                                  relative_delta: float = 0.1, backend: str = "ecosystem") -> str:
    """Perturb each Min-Max or AHP criterion weight and report score and rank sensitivity."""
    return json_result(registry.call(backend, "ecosystem.sensitivity_analysis", {
        "criteria_table": criteria_table, "config": config, "relative_delta": relative_delta, "output": output,
    }))


@mcp.tool()
def get_job_status(backend: str, job_id: str) -> str:
    """Get status, progress, logs, errors, and outputs for an asynchronous software job."""
    return json_result(registry.call(backend, "system.job_status", {"job_id": job_id}))


@mcp.tool()
def cancel_job(backend: str, job_id: str) -> str:
    """Cancel an asynchronous software job when the backend supports cancellation."""
    return json_result(registry.call(backend, "system.cancel_job", {"job_id": job_id}))


@mcp.tool()
def list_job_outputs(backend: str, job_id: str) -> str:
    """List validated files or object-store URLs generated by a software job."""
    return json_result(registry.call(backend, "system.list_outputs", {"job_id": job_id}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.transport == "streamable-http":
        if not is_loopback_host(args.host):
            raise SystemExit("streamable HTTP transport may bind only to localhost/127.0.0.1/::1")
        mcp.settings.host = args.host
        mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
