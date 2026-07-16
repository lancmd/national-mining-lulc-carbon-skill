#!/usr/bin/env python3
"""Local ENVI/IDL command bridge for supervised land-use classification.

The bridge deliberately starts no listener.  It receives one protocol envelope
through standard input, launches the locally configured IDL executable, and
returns one JSON response.  This keeps ENVI control local to the workstation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from path_safety import PathSafetyError, is_unc, require_within
from workflow_agent import ROOT, probe_software


METHODS = {
    "maximum_likelihood": ("envi_maximum_likelihood.pro", "mining_envi_maximum_likelihood"),
    "minimum_distance": ("envi_minimum_distance.pro", "mining_envi_minimum_distance"),
}


def response(envelope: dict[str, Any], status: str, **values: Any) -> dict[str, Any]:
    return {"protocol_version": "1.0", "request_id": envelope.get("request_id"), "status": status, **values}


def safe_local_path(value: Any, label: str, *, output: bool = False) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    if is_unc(value):
        raise PathSafetyError(f"{label} cannot use a UNC/network path")
    path = Path(value).expanduser().resolve()
    if ".." in Path(value).parts:
        raise PathSafetyError(f"{label} cannot use parent-directory traversal")
    if not output and not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path


def output_root() -> Path:
    value = os.getenv("MINING_GIS_OUTPUT_ROOT", str(ROOT / "outputs"))
    if is_unc(value):
        raise PathSafetyError("MINING_GIS_OUTPUT_ROOT cannot be a UNC/network path")
    return Path(value).expanduser().resolve()


def capabilities(envelope: dict[str, Any]) -> dict[str, Any]:
    item = probe_software()["software"]["idl"]
    return response(envelope, "completed", result={
        "backend": "envi",
        "available": item["available"],
        "software_path": item["path"],
        "mode": "local-command",
        "local_only": True,
        "operations": ["system.capabilities", "envi.supervised_classification"],
        "methods": sorted(METHODS),
        "limitation": None if item["available"] else "Configure IDL_EXE or config/local_paths.json after installing licensed ENVI.",
    })


def classify(envelope: dict[str, Any]) -> dict[str, Any]:
    params = envelope.get("parameters", {})
    method = str(params.get("method", "maximum_likelihood")).strip().lower()
    if method not in METHODS:
        return response(envelope, "failed", error=f"unsupported ENVI method: {method}")
    idl = probe_software()["software"]["idl"]["path"]
    if not idl:
        return response(envelope, "failed", error="ENVI/IDL is unavailable; configure a licensed local IDL executable")
    try:
        input_raster = safe_local_path(params.get("input_raster"), "input_raster")
        training_vector = safe_local_path(params.get("training_vector"), "training_vector")
        output_raster = safe_local_path(params.get("output_raster"), "output_raster", output=True)
        require_within(output_raster, [output_root()], "ENVI output_raster")
    except (OSError, PathSafetyError, ValueError) as error:
        return response(envelope, "failed", error=str(error))
    if output_raster.exists() and not bool(params.get("confirm_overwrite")):
        return response(envelope, "failed", error=f"existing output needs confirm_overwrite: {output_raster}")
    batch_name, entrypoint = METHODS[method]
    batch = ROOT / "scripts" / batch_name
    environment = os.environ.copy()
    environment.update({
        "MINING_INPUT_RASTER": str(input_raster),
        "MINING_TRAINING_VECTOR": str(training_vector),
        "MINING_OUTPUT_RASTER": str(output_raster),
    })
    output_raster.parent.mkdir(parents=True, exist_ok=True)
    expression = f".run '{batch.as_posix()}' & {entrypoint} & exit"
    timeout = float(params.get("timeout_seconds", 3600))
    try:
        process = subprocess.run([idl, "-e", expression], cwd=str(output_raster.parent), env=environment,
                                 text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                                 errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return response(envelope, "waiting_interactive", message=f"ENVI/IDL exceeded {timeout:g} seconds; inspect the local session")
    log = output_raster.with_suffix(output_raster.suffix + ".envi.log")
    log.write_text(process.stdout or "", encoding="utf-8")
    if process.returncode:
        return response(envelope, "failed", error=f"ENVI/IDL returned {process.returncode}", log=str(log))
    if not output_raster.exists():
        return response(envelope, "failed", error="ENVI/IDL exited without creating the requested classification raster", log=str(log))
    return response(envelope, "completed", outputs=[str(output_raster)], log=str(log), result={
        "method": method, "input_raster": str(input_raster), "training_vector": str(training_vector),
    })


def main() -> int:
    envelope: dict[str, Any] = {}
    try:
        envelope = json.load(sys.stdin)
        if envelope.get("protocol_version") != "1.0":
            result = response(envelope, "failed", error="unsupported protocol version")
        elif envelope.get("operation") == "system.capabilities":
            result = capabilities(envelope)
        elif envelope.get("operation") == "envi.supervised_classification":
            result = classify(envelope)
        else:
            result = response(envelope, "failed", error=f"unsupported ENVI operation: {envelope.get('operation')}")
    except Exception as error:
        result = response(envelope, "failed", error=str(error))
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
