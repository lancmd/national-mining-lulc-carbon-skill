#!/usr/bin/env python3
"""Backend-neutral MCP server for mining-area GIS operations."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib import request

from mcp.server.fastmcp import FastMCP


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "interfaces" / "backend_registry.json"
EXAMPLE_REGISTRY = ROOT / "interfaces" / "backend_registry.example.json"


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
            "callback_url": None,
        }
        try:
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
        token_env = config.get("token_env")
        if token_env and os.getenv(token_env):
            headers["Authorization"] = f"Bearer {os.environ[token_env]}"
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
        "Execute mining-area GIS tasks through registered software backends. "
        "Call list_backends first, use structured tools, and never claim prepared scripts are completed outputs."
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
def run_gee_export(template: str, variables: dict[str, Any], destination: dict[str, Any], backend: str = "gee") -> str:
    """Submit a parameterized Earth Engine imagery/index/export workflow and return its job id or completed outputs."""
    return json_result(registry.call(backend, "gee.export_imagery", {
        "template": template, "variables": variables, "destination": destination
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
def run_arcgis_operations(spec: dict[str, Any], workspace: str, backend: str = "arcgis") -> str:
    """Run declarative ArcGIS raster/vector operations using a software bridge rather than an installation path."""
    return json_result(registry.call(backend, "arcgis.run_operations", {"spec": spec, "workspace": workspace}))


@mcp.tool()
def run_plus_scenario(project: str, scenario: str, workspace: str,
                      parameters: dict[str, Any] | None = None, backend: str = "plus") -> str:
    """Run a configured PLUS scenario through its registered bridge; do not invent version-specific parameters."""
    return json_result(registry.call(backend, "plus.run_scenario", {
        "project": project, "scenario": scenario, "workspace": workspace, "parameters": parameters or {}
    }))


@mcp.tool()
def run_invest_carbon(datastack: str, workspace: str, backend: str = "invest") -> str:
    """Run InVEST Carbon from a parameter-set/datastack through a registered backend."""
    return json_result(registry.call(backend, "invest.run_carbon", {"datastack": datastack, "workspace": workspace}))


@mcp.tool()
def validate_lulc_model(model_package: str, backend: str = "pytorch") -> str:
    """Validate a portable PyTorch LULC model package, class map, preprocessing contract, and weights hash."""
    return json_result(registry.call(backend, "pytorch.validate_model", {"model_package": model_package}))


@mcp.tool()
def run_pytorch_lulc(model_package: str, input_raster: str, class_output: str,
                     confidence_output: str, device: str = "auto", backend: str = "pytorch") -> str:
    """Run tiled PyTorch LULC inference and create classification and confidence GeoTIFF outputs."""
    return json_result(registry.call(backend, "pytorch.run_lulc_inference", {
        "model_package": model_package, "input_raster": input_raster,
        "class_output": class_output, "confidence_output": confidence_output, "device": device
    }))


@mcp.tool()
def evaluate_ecosystem_services(criteria_table: str, config: str, output: str,
                                backend: str = "ecosystem") -> str:
    """Evaluate ecosystem services with configured Min-Max or AHP weights and write a score table."""
    return json_result(registry.call(backend, "ecosystem.evaluate", {
        "criteria_table": criteria_table, "config": config, "output": output
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
        mcp.settings.host = args.host
        mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
