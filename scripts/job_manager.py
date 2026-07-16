#!/usr/bin/env python3
"""Small local background-job registry for resumable workflow execution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    # A status poll can overlap a worker status update on Windows.  Records are
    # normally replaced atomically; retry also tolerates a pre-existing legacy
    # record written by an earlier version of the worker.
    last_error: Exception | None = None
    for _ in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(0.02)
    raise last_error or OSError(f"cannot read job JSON: {path}")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def job_dir(job_file: Path) -> Path:
    workspace = Path(read_json(job_file)["workspace"]).resolve()
    return workspace / ".jobs"


def record_path(job_file: Path, job_id: str) -> Path:
    return job_dir(job_file) / f"{job_id}.json"


def registry_dir() -> Path:
    """Keep a small local index without scanning arbitrary user directories."""
    root = Path(os.getenv("MINING_GIS_JOB_ROOT", ROOT / "outputs" / ".job_registry")).expanduser().resolve()
    if str(root).startswith("\\\\"):
        raise ValueError("MINING_GIS_JOB_ROOT cannot be a UNC/network path")
    root.mkdir(parents=True, exist_ok=True)
    return root


def index_path(job_id: str) -> Path:
    return registry_dir() / f"{job_id}.json"


def workspace_lock(workspace: Path) -> Path:
    return workspace / ".jobs" / "workflow.lock"


def write_index(record_file: Path, record: dict[str, Any]) -> None:
    write_json(index_path(str(record["job_id"])), {"job_id": record["job_id"], "record": str(record_file.resolve()),
                                                     "workspace": record["workspace"]})


def release_lock(record: dict[str, Any]) -> None:
    lock = workspace_lock(Path(record["workspace"]))
    try:
        payload = read_json(lock)
        if payload.get("job_id") == record.get("job_id"):
            lock.unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError):
        pass


def acquire_lock(workspace: Path, job_id: str, job_file: Path, allow_concurrent: bool) -> None:
    if allow_concurrent:
        return
    lock = workspace_lock(workspace)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            existing = read_json(lock)
            created = datetime.fromisoformat(str(existing.get("created_at"))) if existing.get("created_at") else None
            starting = created and (datetime.now(timezone.utc).astimezone() - created).total_seconds() < 300
            if (existing.get("pid") and alive(existing.get("pid"))) or (not existing.get("pid") and starting):
                raise RuntimeError(f"workflow is already running as local job {existing.get('job_id')}")
        except (json.JSONDecodeError, ValueError):
            pass
        lock.unlink(missing_ok=True)
        return acquire_lock(workspace, job_id, job_file, allow_concurrent)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump({"job_id": job_id, "job_file": str(job_file), "pid": None, "created_at": now()}, stream)


def alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def submit(job_file: Path, dry_run: bool = False, continue_on_error: bool = False,
           confirm_overwrite: bool = False, allow_concurrent: bool = False) -> dict[str, Any]:
    job_file = job_file.resolve()
    workspace = Path(read_json(job_file)["workspace"]).resolve()
    job_id = uuid.uuid4().hex
    acquire_lock(workspace, job_id, job_file, allow_concurrent)
    log = workspace / "logs" / f"background_{job_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    record_file = record_path(job_file, job_id)
    record = {"job_id": job_id, "job_file": str(job_file), "workspace": str(workspace), "pid": None,
              "status": "queued", "started_at": now(), "heartbeat": now(), "log": str(log),
              "options": {"dry_run": dry_run, "continue_on_error": continue_on_error,
                          "confirm_overwrite": confirm_overwrite, "allow_concurrent": allow_concurrent}}
    write_json(record_file, record)
    write_index(record_file, record)
    args = [sys.executable, str(ROOT / "scripts" / "job_worker.py"), "--record", str(record_file)]
    stream = log.open("w", encoding="utf-8")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(args, cwd=workspace, stdout=stream, stderr=subprocess.STDOUT, creationflags=creationflags)
    except Exception:
        release_lock(record)
        raise
    stream.close()
    record.update({"pid": process.pid, "status": "running"})
    write_json(record_file, record)
    lock = workspace_lock(workspace)
    if lock.exists():
        write_json(lock, {"job_id": job_id, "job_file": str(job_file), "pid": process.pid, "created_at": record["started_at"]})
    return record


def find(job_id: str, root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    if root is not None:
        candidate = root.resolve() / ".jobs" / f"{job_id}.json"
    else:
        index = index_path(job_id)
        if not index.is_file():
            raise FileNotFoundError(f"local job record not found: {job_id}")
        candidate = Path(read_json(index).get("record", "")).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"local job record not found: {job_id}")
    record = read_json(candidate)
    if record.get("job_id") != job_id or Path(record.get("workspace", ".")).resolve() not in candidate.parents:
        raise ValueError("job registry record is invalid")
    return candidate, record


def status(job_id: str) -> dict[str, Any]:
    path, record = find(job_id)
    workspace = Path(record["workspace"])
    state_path = workspace / "agent_state.json"
    state = read_json(state_path) if state_path.is_file() else {"stages": {}}
    stages = state.get("stages", {})
    total = len(read_json(Path(record["job_file"])).get("stages", []))
    done = sum(1 for value in stages.values() if value.get("status") in {"completed", "failed", "prepared", "waiting_interactive", "pending_validation"})
    running = alive(record.get("pid"))
    if running:
        record["status"] = "running"
    elif record.get("status") == "running":
        stage_states = {value.get("status") for value in stages.values()}
        record["status"] = ("failed" if "failed" in stage_states else "waiting_interactive" if "waiting_interactive" in stage_states
                            else "prepared" if "prepared" in stage_states else "pending_validation" if "pending_validation" in stage_states
                            else "completed")
        record["finished_at"] = now()
        release_lock(record)
    if Path(record["log"]).is_file():
        record["heartbeat"] = datetime.fromtimestamp(Path(record["log"]).stat().st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds")
    record["progress"] = done / total if total else 1.0 if record["status"] in {"completed", "cancelled"} else 0.0
    record["stage_statuses"] = stages
    write_json(path, record)
    return record


def cancel(job_id: str) -> dict[str, Any]:
    path, record = find(job_id)
    if alive(record.get("pid")):
        command = ["taskkill", "/PID", str(record["pid"]), "/T", "/F"] if os.name == "nt" else ["kill", "-TERM", str(record["pid"])]
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or "could not cancel local job")
    record.update({"status": "cancelled", "cancelled_at": now()})
    write_json(path, record)
    release_lock(record)
    return record


def outputs(job_id: str) -> dict[str, Any]:
    record = status(job_id)
    workspace = Path(record["workspace"])
    manifest = workspace / "outputs_manifest.json"
    payload = read_json(manifest) if manifest.is_file() else {}
    return {"job_id": job_id, "status": record["status"], "manifest": str(manifest) if manifest.is_file() else None,
            "outputs": payload.get("artifacts", []), "workspace": str(workspace)}
