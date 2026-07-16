#!/usr/bin/env python3
"""Local-only PLUS bridge wrapper.

The configured bridge reads one protocol envelope from standard input and emits one
protocol response on standard output.  The repository does not infer a PLUS GUI or
command-line interface: a locally installed PLUS version needs an explicit bridge.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from path_safety import PathSafetyError, is_unc, require_within
from plus_contract import expected_plus_raster


ROOT = Path(__file__).resolve().parents[1]
VALID_STATUSES = {"accepted", "running", "completed", "prepared", "pending_validation", "waiting_interactive", "failed", "cancelled"}


def response(envelope: dict[str, Any], status: str, **values: Any) -> dict[str, Any]:
    return {"protocol_version": "1.0", "request_id": envelope.get("request_id"), "status": status, **values}


def expand_command_item(value: str) -> str:
    """Expand portable local-bridge placeholders without embedding machine paths."""
    return os.path.expandvars(value.replace("{python}", sys.executable).replace("{skill_root}", str(ROOT)))


def bridge_command() -> list[str]:
    value = os.getenv("MINING_PLUS_BRIDGE_COMMAND", "").strip()
    if not value:
        configured = Path(os.getenv("MINING_GIS_LOCAL_PATHS", ROOT / "config" / "local_paths.json")).expanduser()
        if configured.exists():
            payload = json.loads(configured.read_text(encoding="utf-8-sig"))
            command = payload.get("plus_bridge_command", [])
            if isinstance(command, list) and all(isinstance(item, str) and item for item in command):
                return [expand_command_item(item) for item in command]
    if not value:
        return []
    if value.startswith("["):
        parsed = json.loads(value)
        if not isinstance(parsed, list) or not all(isinstance(item, str) and item for item in parsed):
            raise ValueError("MINING_PLUS_BRIDGE_COMMAND JSON value must be a non-empty command array")
        return [expand_command_item(item) for item in parsed]
    return [expand_command_item(item) for item in shlex.split(value, posix=False)]


def scenario_paths(envelope: dict[str, Any]) -> tuple[str, Path, Path]:
    parameters = envelope.get("parameters", {})
    detail = parameters.get("parameters", {}) if isinstance(parameters.get("parameters"), dict) else {}
    scenario = str(parameters.get("scenario", "scenario")).strip().upper()
    raw_workspace = detail.get("output_directory") or parameters.get("workspace", ROOT / "outputs" / "plus_prepared")
    if is_unc(raw_workspace):
        raise PathSafetyError("PLUS workspace cannot be a UNC/network path")
    workspace = Path(raw_workspace).expanduser().resolve()
    project_file = parameters.get("project")
    if isinstance(project_file, str) and Path(project_file).expanduser().is_file():
        from project_validator import validate
        report = validate(Path(project_file).expanduser().resolve())
        if report.get("status") != "valid":
            raise ValueError("PLUS project is no longer valid: " + "; ".join(report.get("errors", [])))
        require_within(workspace, [Path(report["workspace"])], "PLUS scenario workspace")
    else:
        root_value = os.getenv("MINING_PLUS_OUTPUT_ROOT")
        if not root_value:
            raise ValueError("PLUS requires an existing project.json or MINING_PLUS_OUTPUT_ROOT")
        require_within(workspace, [Path(root_value).expanduser().resolve()], "PLUS scenario workspace")
    expected = Path(detail.get("expected_output") or expected_plus_raster(workspace, scenario)).expanduser().resolve()
    try:
        expected.relative_to(workspace)
    except ValueError as error:
        raise ValueError("PLUS expected_output must be inside this scenario workspace") from error
    return scenario, workspace, expected


def write_request_pack(envelope: dict[str, Any]) -> tuple[str, str]:
    scenario, workspace, expected = scenario_paths(envelope)
    workspace.mkdir(parents=True, exist_ok=True)
    pack = workspace / f"plus_local_request_{scenario}.json"
    pack.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # The version-specific GUI bridge owns plus_execution_state.json.  Keeping
    # this generic request receipt separate prevents a resumed workflow from
    # erasing a live GUI PID and its completed-step checkpoint.
    state = workspace / "plus_backend_request_state.json"
    state.write_text(json.dumps({"scenario": scenario, "status": "prepared", "request": str(pack),
                                 "expected_output": str(expected)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(pack), str(state)


def adopt_existing_output(envelope: dict[str, Any]) -> dict[str, Any] | None:
    scenario, workspace, expected = scenario_paths(envelope)
    if not expected.is_file():
        return None
    if expected.suffix.lower() not in {".tif", ".tiff"}:
        return response(envelope, "failed", error=f"PLUS {scenario} output is not a GeoTIFF: {expected}")
    minimum_age = float(os.getenv("MINING_PLUS_OUTPUT_STABLE_SECONDS", "5"))
    stat = expected.stat()
    if stat.st_size <= 8 or time.time() - stat.st_mtime < minimum_age:
        return response(envelope, "waiting_interactive", outputs=[str(expected)],
                        message=f"PLUS {scenario} GeoTIFF is still being written; wait at least {minimum_age:g} seconds before adoption")
    with expected.open("rb") as stream:
        signature = stream.read(4)
    if signature not in {b"II*\x00", b"MM\x00*"}:
        return response(envelope, "failed", error=f"PLUS {scenario} output is not a readable TIFF signature: {expected}")
    state = workspace / "plus_execution_state.json"
    workspace.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"scenario": scenario, "status": "completed", "adopted": True,
                                 "expected_output": str(expected)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return response(envelope, "completed", outputs=[str(expected)],
                    message="adopted an existing local PLUS scenario output")


def normalize_bridge_result(envelope: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Accept a bridge result only when it identifies the contracted LULC raster."""
    if result.get("status") != "completed":
        return result
    scenario, workspace, expected = scenario_paths(envelope)
    candidates = [str(item) for item in result.get("outputs", []) if isinstance(item, str)]
    nested = result.get("result")
    if isinstance(nested, dict):
        for key in ("landuse_raster", "lulc_raster", "output_raster"):
            if isinstance(nested.get(key), str):
                candidates.append(nested[key])
    if expected.exists():
        candidates.append(str(expected))
    valid = [str(Path(item).expanduser().resolve()) for item in candidates
             if Path(item).expanduser().is_file() and Path(item).suffix.lower() in {".tif", ".tiff"}]
    if str(expected) not in valid:
        return response(envelope, "failed", error=("local PLUS bridge reported completed but did not create the "
                                                     f"contracted scenario LULC raster: {expected}"))
    result["outputs"] = [str(expected)]
    result.setdefault("message", "local PLUS scenario output accepted")
    (workspace / "plus_execution_state.json").write_text(json.dumps({"scenario": scenario, "status": "completed",
        "adopted": False, "expected_output": str(expected)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def inspect_bridge(command: list[str], envelope: dict[str, Any]) -> dict[str, Any] | None:
    """Ask a configured local bridge for its own declared capabilities.

    This is a read-only protocol request.  It avoids guessing a vendor version
    from the bridge command or its file name.
    """
    if not command:
        return None
    probe = {"protocol_version": "1.0", "request_id": envelope.get("request_id"),
             "operation": "system.capabilities", "parameters": {}}
    try:
        process = subprocess.run(command, input=json.dumps(probe, ensure_ascii=True), text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                 errors="replace", timeout=30, check=False)
        if process.returncode:
            return {"available": False, "error": process.stderr.strip() or f"bridge returned {process.returncode}"}
        result = json.loads(process.stdout)
        if result.get("status") != "completed" or not isinstance(result.get("result"), dict):
            return {"available": False, "error": result.get("error", "bridge did not return capabilities")}
        return {"available": True, **result["result"]}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        return {"available": False, "error": str(error)}


def main() -> int:
    envelope: dict[str, Any] = {}
    try:
        envelope = json.load(sys.stdin)
        operation = envelope.get("operation")
        if envelope.get("protocol_version") != "1.0":
            result = response(envelope, "failed", error="unsupported protocol version")
        elif operation == "system.capabilities":
            command = bridge_command()
            result = response(envelope, "completed", result={
                "backend": "plus", "mode": "local-command-bridge", "local_only": True,
                "bridge_configured": bool(command),
                "bridge_capabilities": inspect_bridge(command, envelope),
                "operations": ["system.capabilities", "plus.calibrate", "plus.run_scenario"],
            })
        elif operation not in {"plus.run_scenario", "plus.calibrate"}:
            result = response(envelope, "failed", error=f"unsupported PLUS operation: {operation}")
        elif operation == "plus.calibrate":
            command = bridge_command()
            if not command:
                result = response(envelope, "failed", error="local PLUS bridge is not configured")
            else:
                # Calibration may cross a local UAC boundary before the
                # elevated UI Automation worker can attach.  Two minutes was
                # shorter than that normal local handoff and turned an in-progress
                # calibration into a false bridge failure.
                calibration_timeout = float(envelope.get("parameters", {}).get("timeout_seconds", 300))
                if not 30 <= calibration_timeout <= 900:
                    raise ValueError("PLUS calibration timeout_seconds must be between 30 and 900")
                process = subprocess.run(command, input=json.dumps(envelope, ensure_ascii=True), text=True,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                         errors="replace", timeout=calibration_timeout, check=False)
                result = (response(envelope, "failed", error=process.stderr.strip() or f"local PLUS bridge returned {process.returncode}")
                          if process.returncode else json.loads(process.stdout))
        else:
            adopted = adopt_existing_output(envelope)
            command = bridge_command()
            if adopted:
                result = adopted
            elif not command:
                pack, state = write_request_pack(envelope)
                result = response(envelope, "prepared", outputs=[pack, state],
                                  message="local PLUS bridge is not configured; task pack is ready for the installed PLUS version")
            else:
                # GUI bridges use this persisted request when the user resumes a scenario.
                write_request_pack(envelope)
                process = subprocess.run(command, input=json.dumps(envelope, ensure_ascii=True), text=True,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                         errors="replace", timeout=3600, check=False)
                if process.returncode:
                    result = response(envelope, "failed", error=process.stderr.strip() or f"local PLUS bridge returned {process.returncode}")
                else:
                    result = normalize_bridge_result(envelope, json.loads(process.stdout))
                    if result.get("status") not in VALID_STATUSES:
                        raise ValueError("local PLUS bridge returned an unsupported status")
                    result.setdefault("protocol_version", "1.0")
                    result.setdefault("request_id", envelope.get("request_id"))
    except Exception as error:
        result = response(envelope, "failed", error=str(error))
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
