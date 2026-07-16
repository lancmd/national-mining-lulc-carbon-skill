#!/usr/bin/env python3
"""Cross-software workflow runner for the mining LULC/carbon skill."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from artifact_manifest import write_records
from path_safety import PathSafetyError, is_unc, require_within, resolved


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def first_existing(candidates: list[str | None]) -> str | None:
    for item in candidates:
        if item and Path(item).exists():
            return str(Path(item).resolve())
    return None


def arcgis_registry_paths() -> tuple[str | None, str | None]:
    """Find a standard ArcGIS Pro installation without committing a user path.

    ArcGIS Pro records its installation directory in the Windows registry.  This
    is a read-only discovery step and remains behind explicit local-path and
    environment-variable overrides.  Non-Windows hosts intentionally return no
    candidates.
    """
    if sys.platform != "win32":
        return None, None
    try:
        import winreg  # type: ignore[attr-defined]
        for key_name in (r"SOFTWARE\ESRI\ArcGISPro", r"SOFTWARE\WOW6432Node\ESRI\ArcGISPro"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_name) as key:
                    install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
            except OSError:
                continue
            root = Path(str(install_dir)).expanduser()
            propy = root / "bin" / "Python" / "scripts" / "propy.bat"
            application = root / "bin" / "ArcGISPro.exe"
            return str(propy), str(application)
    except (ImportError, OSError):
        pass
    return None, None


def software_version(name: str, executable: str | None) -> str | None:
    """Probe command-line versions where the vendor executable documents one safely."""
    if not executable or name not in {"invest", "gdalinfo"}:
        return None
    try:
        process = subprocess.run([executable, "--version"], text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                                 timeout=10, check=False)
        return (process.stdout or "").strip().splitlines()[0] if process.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def local_paths() -> dict[str, Any]:
    """Read optional machine-specific paths without committing them to the repository."""
    configured = os.getenv("MINING_GIS_LOCAL_PATHS")
    path = Path(configured).expanduser() if configured else ROOT / "config" / "local_paths.json"
    if not path.exists():
        return {}
    try:
        payload = load_json(path.resolve())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read local paths configuration: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("local paths configuration must be a JSON object")
    return {str(key): os.path.expandvars(value) if isinstance(value, str) else value
            for key, value in payload.items()}


def probe_software(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    overrides = overrides or {}
    configured = local_paths()
    registry_propy, registry_arcgis = arcgis_registry_paths()
    path_candidates = {
        "arcgis_propy": [
            overrides.get("arcgis_propy"), configured.get("arcgis_propy"), os.getenv("ARCGIS_PROPY"),
            shutil.which("propy.bat"), registry_propy,
        ],
        "arcgis_pro": [
            overrides.get("arcgis_pro"), configured.get("arcgis_pro"), os.getenv("ARCGIS_PRO_EXE"),
            shutil.which("ArcGISPro.exe"), registry_arcgis,
        ],
        "invest": [
            overrides.get("invest"), configured.get("invest"), os.getenv("INVEST_CLI"), shutil.which("invest"),
        ],
        "idl": [
            overrides.get("idl"), configured.get("idl"), os.getenv("IDL_EXE"), shutil.which("idl"),
        ],
        "plus": [overrides.get("plus"), configured.get("plus_v142_executable"), configured.get("plus"),
                 os.getenv("PLUS_V142_EXECUTABLE"), os.getenv("PLUS_EXE"), shutil.which("PLUS V1.4.2.exe")],
        "gdalinfo": [
            overrides.get("gdalinfo"), configured.get("gdalinfo"), os.getenv("GDALINFO"), shutil.which("gdalinfo"),
        ],
    }
    result: dict[str, Any] = {"probed_at": now(), "platform": sys.platform, "software": {}}
    for name, candidates in path_candidates.items():
        executable = first_existing(candidates)
        result["software"][name] = {"available": bool(executable), "path": executable,
                                    "version": software_version(name, executable)}
    return result


class JobRunner:
    def __init__(self, job_path: Path, dry_run: bool = False, continue_on_error: bool = False,
                 confirm_overwrite: bool = False):
        self.job_path = job_path.resolve()
        self.job_dir = self.job_path.parent
        self.job = load_json(self.job_path)
        self.job["_path"] = str(self.job_path)
        if self.job.get("schema_version") != 1:
            raise ValueError("Only workflow job schema_version 1 is supported")
        if is_unc(self.job.get("workspace", "")):
            raise PathSafetyError("workflow workspace cannot be a UNC/network path")
        self.workspace = self.resolve(self.job.get("workspace", "outputs/job"), self.job_dir)
        security = self.job.get("security", {}) if isinstance(self.job.get("security", {}), dict) else {}
        self.output_root = self.resolve(security.get("output_root", str(self.workspace)), self.job_dir)
        require_within(self.workspace, [self.output_root], "workflow workspace")
        raw_input_roots = security.get("input_roots", [str(self.job_dir)])
        self.input_roots = [self.resolve(str(item), self.job_dir) for item in raw_input_roots]
        self.workspace.mkdir(parents=True, exist_ok=True)
        for folder in ("logs", "generated", "intermediate", "outputs", "validation"):
            (self.workspace / folder).mkdir(exist_ok=True)
        self.state_path = self.workspace / "agent_state.json"
        self.state = load_json(self.state_path) if self.state_path.exists() else {
            "project_id": self.job.get("project_id"), "created_at": now(), "stages": {}
        }
        self.probe = probe_software(self.job.get("software"))
        write_json(self.workspace / "software_probe.json", self.probe)
        self.dry_run = dry_run
        self.continue_on_error = continue_on_error
        self.confirm_overwrite = confirm_overwrite or bool(security.get("confirm_overwrite", False))

    @staticmethod
    def resolve(value: str, base: Path) -> Path:
        path = Path(os.path.expandvars(value)).expanduser()
        return path.resolve() if path.is_absolute() else (base / path).resolve()

    def stage_path(self, value: str) -> Path:
        if is_unc(value):
            raise PathSafetyError(f"UNC/network path is not allowed: {value}")
        path = Path(os.path.expandvars(value)).expanduser()
        if path.is_absolute():
            return path.resolve()
        job_candidate = (self.job_dir / path).resolve()
        if job_candidate.exists():
            return job_candidate
        root_candidate = (ROOT / path).resolve()
        if root_candidate.exists():
            return root_candidate
        return (self.workspace / path).resolve()

    def output_path(self, value: str) -> Path:
        path = self.stage_path(value)
        return require_within(path, [self.workspace], "stage output")

    def save_state(self) -> None:
        self.state["updated_at"] = now()
        write_json(self.state_path, self.state)

    def declared_outputs_exist(self, stage: dict[str, Any]) -> bool:
        outputs = stage.get("outputs", [])
        return bool(outputs) and all(self.output_path(item).exists() for item in outputs)

    def validate_stage(self, stage: dict[str, Any]) -> list[str]:
        errors = []
        if not stage.get("id") or not stage.get("adapter"):
            errors.append("stage requires id and adapter")
        for value in stage.get("inputs", []):
            try:
                path = self.stage_path(value)
                if not (path.exists() and (path.is_relative_to(self.workspace) or any(
                        path.is_relative_to(root) for root in self.input_roots))):
                    errors.append(f"missing or disallowed input: {value}")
            except (OSError, PathSafetyError, TypeError) as error:
                errors.append(f"invalid input {value}: {error}")
        inputs = {str(self.stage_path(value)) for value in stage.get("inputs", []) if isinstance(value, str)}
        for value in stage.get("outputs", []):
            try:
                path = self.output_path(value)
                if str(path) in inputs:
                    errors.append(f"stage output would overwrite an input: {path}")
                prior = self.state.get("stages", {}).get(stage.get("id", ""), {})
                takeover = stage.get("adapter") == "plus" and prior.get("status") in {"prepared", "waiting_interactive"}
                if path.exists() and not self.confirm_overwrite and not takeover:
                    errors.append(f"existing output needs --confirm-overwrite: {path}")
            except (OSError, PathSafetyError, TypeError) as error:
                errors.append(f"invalid output {value}: {error}")
        adapter = stage.get("adapter")
        timeout = stage.get("timeout_seconds")
        if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
            errors.append("timeout_seconds must be a positive number when supplied")
        retries = stage.get("retries", 0)
        if not isinstance(retries, int) or not 0 <= retries <= 5:
            errors.append("retries must be an integer from 0 to 5")
        required = {"arcgis": "arcgis_propy", "invest": "invest", "envi": "idl"}.get(adapter)
        if required and not self.probe["software"][required]["available"]:
            errors.append(f"software unavailable: {required}")
        return errors

    def plan(self) -> dict[str, Any]:
        stages = []
        for stage in self.job.get("stages", []):
            if not stage.get("enabled", False):
                status, issues = "disabled", []
            else:
                issues = self.validate_stage(stage)
                status = "blocked" if issues else "ready"
            stages.append({"id": stage.get("id"), "adapter": stage.get("adapter"),
                           "status": status, "issues": issues})
        return {"project_id": self.job.get("project_id"), "workspace": str(self.workspace),
                "software": self.probe["software"], "stages": stages}

    def command(self, stage_id: str, args: list[str], env: dict[str, str] | None = None,
                timeout_seconds: float | None = None, retries: int = 0) -> dict[str, Any]:
        log_path = self.workspace / "logs" / f"{stage_id}.log"
        if self.dry_run:
            return {"status": "prepared", "command": args, "log": f"logs/{stage_id}.log", "dry_run": True}
        timeout = float(timeout_seconds) if timeout_seconds is not None else 3600.0
        attempts: list[str] = []
        for attempt in range(retries + 1):
            try:
                process = subprocess.run(args, cwd=self.workspace, env=env, text=True,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         encoding="utf-8", errors="replace", timeout=timeout, check=False)
                attempts.append(f"attempt {attempt + 1}: returncode={process.returncode}\n{process.stdout or ''}")
                if process.returncode == 0:
                    log_path.write_text("\n\n".join(attempts), encoding="utf-8")
                    return {"status": "completed", "command": args, "returncode": process.returncode,
                            "attempts": attempt + 1, "timeout_seconds": timeout, "log": f"logs/{stage_id}.log"}
            except subprocess.TimeoutExpired as error:
                attempts.append(f"attempt {attempt + 1}: timeout after {timeout:g} seconds\n{error.stdout or ''}")
        log_path.write_text("\n\n".join(attempts), encoding="utf-8")
        raise RuntimeError(f"command failed after {retries + 1} attempt(s); see {log_path}")

    def run_arcgis(self, stage: dict[str, Any]) -> dict[str, Any]:
        propy = self.probe["software"]["arcgis_propy"]["path"]
        spec = self.stage_path(stage["spec"])
        command = [propy, str(ROOT / "scripts" / "arcgis_ops.py"), "--spec", str(spec), "--workspace", str(self.workspace)]
        if self.confirm_overwrite:
            command.append("--confirm-overwrite")
        return self.command(stage["id"], command, timeout_seconds=stage.get("timeout_seconds"), retries=stage.get("retries", 0))

    def run_invest(self, stage: dict[str, Any]) -> dict[str, Any]:
        executable = self.probe["software"]["invest"]["path"]
        datastack = self.stage_path(stage["datastack"])
        payload = load_json(datastack)
        if not payload.get("invest_version"):
            version_process = subprocess.run([executable, "--version"], text=True, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", check=False)
            version = (version_process.stdout or "").strip().splitlines()[-1] if version_process.stdout else ""
            if version_process.returncode or not re.match(r"^\d+(?:\.\d+)+", version):
                raise RuntimeError("cannot determine the local InVEST version for the generated datastack")
            payload["invest_version"] = version
            datastack = self.workspace / "generated" / f"{stage['id']}_runtime_datastack.json"
            write_json(datastack, payload)
        model_workspace = self.stage_path(stage.get("model_workspace", f"outputs/{stage['id']}"))
        model_workspace.mkdir(parents=True, exist_ok=True)
        args = [executable, "run", stage.get("model", "carbon"), "-l", "-d", str(datastack),
                "-w", str(model_workspace)]
        return self.command(stage["id"], args, timeout_seconds=stage.get("timeout_seconds"), retries=stage.get("retries", 0))

    def run_envi(self, stage: dict[str, Any]) -> dict[str, Any]:
        executable = self.probe["software"]["idl"]["path"]
        batch = self.stage_path(stage.get("batch_file", "scripts/envi_maximum_likelihood.pro"))
        entrypoint = stage.get("entrypoint", "mining_envi_maximum_likelihood")
        env = os.environ.copy()
        env.update({str(key): str(self.stage_path(value)) for key, value in stage.get("env", {}).items()})
        expression = f".run '{batch.as_posix()}' & {entrypoint} & exit"
        return self.command(stage["id"], [executable, "-e", expression], env=env,
                            timeout_seconds=stage.get("timeout_seconds"), retries=stage.get("retries", 0))

    def run_plus(self, stage: dict[str, Any]) -> dict[str, Any]:
        if stage.get("request"):
            envelope = dict(stage["request"])
            parameters = dict(envelope.get("parameters", {}))
            parameters.setdefault("workspace", str(self.workspace / "outputs" / "plus"))
            envelope["parameters"] = parameters
            log_path = self.workspace / "logs" / f"{stage['id']}.log"
            if self.dry_run:
                return {"status": "prepared", "request": envelope, "log": str(log_path), "dry_run": True}
            timeout = float(stage.get("timeout_seconds", 3600))
            try:
                process = subprocess.run([sys.executable, str(ROOT / "scripts" / "plus_backend.py")],
                                         input=json.dumps(envelope, ensure_ascii=True), text=True,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                                         errors="replace", timeout=timeout, check=False)
            except subprocess.TimeoutExpired as error:
                log_path.write_text(str(error), encoding="utf-8")
                raise RuntimeError(f"local PLUS bridge timed out after {timeout:g} seconds; see {log_path}") from error
            log_path.write_text(process.stdout or "", encoding="utf-8")
            if process.returncode:
                raise RuntimeError(f"local PLUS bridge returned {process.returncode}; see {log_path}")
            result = json.loads(process.stdout)
            if result.get("status") == "failed":
                raise RuntimeError(result.get("error", "local PLUS bridge failed"))
            return {"status": result.get("status", "failed"), "outputs": result.get("outputs", []),
                    "message": result.get("message"), "log": str(log_path)}
        executable = stage.get("executable") or self.probe["software"]["plus"]["path"]
        if stage.get("command_args"):
            if not executable:
                raise RuntimeError("PLUS executable is unavailable")
            return self.command(stage["id"], [executable, *map(str, stage["command_args"])],
                                timeout_seconds=stage.get("timeout_seconds"), retries=stage.get("retries", 0))
        if stage.get("launch_gui") and executable:
            if self.dry_run:
                return {"status": "prepared", "command": [executable], "dry_run": True}
            subprocess.Popen([executable], cwd=self.workspace)
            return {"status": "waiting_interactive", "reason": "PLUS GUI launched"}
        return {"status": "prepared", "reason": "inputs prepared; no verified PLUS automation entry supplied"}

    def run_command(self, stage: dict[str, Any]) -> dict[str, Any]:
        return self.command(stage["id"], [str(item) for item in stage["command"]],
                            timeout_seconds=stage.get("timeout_seconds"), retries=stage.get("retries", 0))

    def run(self, selected_stage: str | None = None) -> int:
        failures = 0
        self.state["workflow"] = {"status": "running", "resumed_at": now()}
        self.save_state()
        paused = False
        enabled_ids = {item["id"] for item in self.job.get("stages", []) if item.get("enabled")}
        for stage in self.job.get("stages", []):
            stage_id = stage.get("id", "unnamed")
            if not stage.get("enabled") or (selected_stage and stage_id != selected_stage):
                continue
            previous = self.state["stages"].get(stage_id, {})
            if previous.get("status") == "completed" and self.declared_outputs_exist(stage):
                print(f"SKIP {stage_id}: completed outputs still exist")
                continue
            dependencies = stage.get("depends_on", [])
            bad_dependencies = [item for item in dependencies if item not in enabled_ids or
                                self.state["stages"].get(item, {}).get("status") != "completed"]
            errors = self.validate_stage(stage)
            if bad_dependencies:
                errors.append(f"dependencies not completed: {', '.join(bad_dependencies)}")
            record: dict[str, Any] = {"adapter": stage.get("adapter"), "started_at": now()}
            self.state["stages"][stage_id] = record
            self.save_state()
            try:
                if errors:
                    raise RuntimeError("; ".join(errors))
                adapter = stage["adapter"]
                handler = getattr(self, f"run_{adapter}", None)
                if handler is None:
                    raise ValueError(f"unsupported adapter: {adapter}")
                result = handler(stage)
                record.update(result)
                if record["status"] == "completed" and stage.get("outputs") and not self.declared_outputs_exist(stage):
                    raise RuntimeError("command succeeded but one or more declared outputs are missing")
                print(f"{record['status'].upper()} {stage_id}")
                if record["status"] in {"waiting_interactive", "prepared", "pending_validation"}:
                    # A GUI handoff is a deliberate pause, not a failed
                    # dependency.  The next resume rechecks this exact stage;
                    # when its declared raster appears, downstream stages run.
                    paused = True
                    self.state["workflow"] = {"status": "paused", "reason": record["status"],
                                              "paused_at_stage": stage_id, "paused_at": now()}
            except Exception as error:
                record.update({"status": "failed", "error": str(error)})
                failures += 1
                print(f"FAILED {stage_id}: {error}", file=sys.stderr)
            finally:
                record["finished_at"] = now()
                self.save_state()
            if paused:
                break
            if failures and not self.continue_on_error:
                break
        if not failures and not paused:
            self.state["workflow"] = {"status": "completed", "completed_at": now()}
            self.save_state()
        try:
            records = write_records(self.workspace, self.job, self.state, self.probe)
            self.state["records"] = records
            self.save_state()
        except Exception as error:
            self.state["records_error"] = str(error)
            self.save_state()
            failures += 1
        return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    probe = sub.add_parser("probe", help="detect supported software")
    probe.add_argument("--output", type=Path)
    for name in ("plan", "run"):
        command = sub.add_parser(name)
        command.add_argument("--job", required=True, type=Path)
        if name == "run":
            command.add_argument("--stage")
            command.add_argument("--dry-run", action="store_true")
            command.add_argument("--continue-on-error", action="store_true")
            command.add_argument("--confirm-overwrite", action="store_true")
    args = parser.parse_args()
    if args.action == "probe":
        result = probe_software()
        if args.output:
            write_json(args.output.resolve(), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    runner = JobRunner(args.job, getattr(args, "dry_run", False),
                       getattr(args, "continue_on_error", False), getattr(args, "confirm_overwrite", False))
    if args.action == "plan":
        print(json.dumps(runner.plan(), ensure_ascii=False, indent=2))
        return 0
    return runner.run(args.stage)


if __name__ == "__main__":
    raise SystemExit(main())
