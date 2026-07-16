#!/usr/bin/env python3
"""Local GUI bridge pinned to one official HPSCIL PLUS repository snapshot.

The selected official repository snapshot contains an executable named
``PLUS V1.4.2.exe`` but its live Qt window identifies itself as V1.4.1 and the
repository has no tagged release.  The bridge records this evidence instead of
asserting a vendor version from the file name.  It automates the local window
with an explicitly calibrated profile and never invents menu names, dialog
controls, or command-line arguments.  UI Automation through :mod:`pywinauto`
is preferred; a screenshot template is only a local fallback.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from path_safety import PathSafetyError, is_unc, require_within
from plus_contract import expected_plus_raster


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_NAME = "plus_v142_gui_automation"
SOFTWARE_NAME = "HPSCIL official PLUS snapshot"
EXE_FILE_LABEL = "PLUS V1.4.2.exe"
OBSERVED_UI_TITLE = "Patch-generating Land Use Simulation (PLUS) Model V1.4.1"
OFFICIAL_REMOTE = "https://github.com/HPSCIL/Patch-generating_Land_Use_Simulation_Model.git"
PINNED_COMMIT = "de7ba6efd35b530da6c37e81103276a17716602c"
PINNED_EXECUTABLE = "PLUS V1.4.2.exe"
PINNED_SHA256 = "2f49f4f01c0a209d0d67fabef9013d41fca30b1632e334898abadad5c2eb25d4"
VALID_SCENARIOS = {"ND", "UD", "EP", "RE"}


class GuiAutomationError(RuntimeError):
    """A profile cannot safely operate the current local PLUS window."""


def response(envelope: dict[str, Any], status: str, **values: Any) -> dict[str, Any]:
    return {"protocol_version": "1.0", "request_id": envelope.get("request_id"), "status": status, **values}


def read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_local_paths() -> dict[str, Any]:
    configured = Path(os.getenv("MINING_GIS_LOCAL_PATHS", ROOT / "config" / "local_paths.json")).expanduser()
    payload = read_json(configured, {})
    return payload if isinstance(payload, dict) else {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_remote(value: str) -> str:
    return value.strip().replace("\\", "/").rstrip("/").removesuffix(".git").lower()


def git_identity(repository: Path) -> tuple[str, str]:
    """Read the origin URL and checked-out SHA without relying on a Git binary."""
    dot_git = repository / ".git"
    if not dot_git.is_dir():
        raise ValueError("official PLUS snapshot does not contain .git metadata")
    config = (dot_git / "config").read_text(encoding="utf-8", errors="replace")
    origin = re.search(r'\[remote "origin"\][^\[]*?^\s*url\s*=\s*(.+?)\s*$', config, flags=re.MULTILINE | re.DOTALL)
    if not origin:
        raise ValueError("official PLUS snapshot has no origin remote")
    head = (dot_git / "HEAD").read_text(encoding="ascii", errors="replace").strip()
    if head.startswith("ref: "):
        ref = head[5:].strip()
        reference = dot_git / ref
        if reference.is_file():
            commit = reference.read_text(encoding="ascii", errors="replace").strip()
        else:
            packed = dot_git / "packed-refs"
            lines = packed.read_text(encoding="ascii", errors="replace").splitlines() if packed.is_file() else []
            commit = next((line.split(" ", 1)[0] for line in lines if line.endswith(" " + ref)), "")
    else:
        commit = head
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("cannot resolve the checked-out official PLUS snapshot commit")
    return origin.group(1).strip(), commit.lower()


def configured_installation() -> tuple[Path, Path, dict[str, Any]]:
    """Return the one approved local official release, or raise a useful error."""
    local = load_local_paths()
    repo_raw = os.getenv("PLUS_V142_REPOSITORY") or local.get("plus_v142_repository")
    executable_raw = os.getenv("PLUS_V142_EXECUTABLE") or local.get("plus_v142_executable") or local.get("plus")
    if not isinstance(repo_raw, str) or not repo_raw.strip() or not isinstance(executable_raw, str) or not executable_raw.strip():
        raise ValueError("configure plus_v142_repository and plus_v142_executable in config/local_paths.json")
    if is_unc(repo_raw) or is_unc(executable_raw):
        raise PathSafetyError("official PLUS snapshot must be installed on a local drive, not a UNC/network path")
    repository = Path(os.path.expandvars(repo_raw)).expanduser().resolve()
    executable = Path(os.path.expandvars(executable_raw)).expanduser().resolve()
    if not repository.is_dir() or not executable.is_file():
        raise ValueError("configured official PLUS snapshot repository or executable does not exist")
    if executable.name != PINNED_EXECUTABLE:
        raise ValueError(f"official snapshot bridge only accepts the repository executable named {PINNED_EXECUTABLE}")
    require_within(executable, [repository], "official PLUS snapshot executable")
    origin, commit = git_identity(repository)
    if normalize_remote(origin) != normalize_remote(OFFICIAL_REMOTE):
        raise ValueError("PLUS snapshot origin is not the approved HPSCIL official repository")
    if commit != PINNED_COMMIT:
        raise ValueError(f"official PLUS snapshot checkout is {commit}, expected pinned commit {PINNED_COMMIT}")
    claimed_version = str(local.get("plus_v142_version") or "unverified").strip()
    claimed_hash = str(local.get("plus_v142_sha256") or PINNED_SHA256).strip().lower()
    claimed_commit = str(local.get("plus_v142_commit") or PINNED_COMMIT).strip().lower()
    actual_hash = sha256(executable)
    if claimed_commit != PINNED_COMMIT or claimed_hash != PINNED_SHA256:
        raise ValueError("local PLUS snapshot identity fields do not match the pinned official binary")
    if actual_hash != PINNED_SHA256:
        raise ValueError("official PLUS snapshot executable SHA-256 differs from the pinned binary")
    identity = {
        "software": SOFTWARE_NAME,
        "version_evidence": {
            "repository_executable_filename": EXE_FILE_LABEL,
            "configured_label": claimed_version,
            "observed_ui_title": OBSERVED_UI_TITLE,
            "vendor_release_status": "unverified: no repository tag or GitHub release",
        },
        "repository": str(repository),
        "origin": origin,
        "commit": commit,
        "executable": str(executable),
        "sha256": actual_hash,
        "size_bytes": executable.stat().st_size,
    }
    return repository, executable, identity


def pid_is_alive(pid: Any) -> bool:
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


def scenario_paths(envelope: dict[str, Any]) -> tuple[str, Path, Path, Path, Path]:
    parameters = envelope.get("parameters", {})
    detail = parameters.get("parameters", {}) if isinstance(parameters.get("parameters"), dict) else {}
    scenario = str(parameters.get("scenario", "")).strip().upper()
    if scenario not in VALID_SCENARIOS:
        raise ValueError("official HPSCIL PLUS snapshot supports only ND, UD, EP, or RE scenarios")
    raw_workspace = detail.get("output_directory") or parameters.get("workspace")
    if not isinstance(raw_workspace, str) or not raw_workspace:
        raise ValueError("official HPSCIL PLUS bridge needs a per-scenario output_directory")
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
        output_root = os.getenv("MINING_PLUS_OUTPUT_ROOT")
        if not output_root:
            raise ValueError("PLUS requires an existing project.json or MINING_PLUS_OUTPUT_ROOT")
        require_within(workspace, [Path(output_root).expanduser().resolve()], "PLUS scenario workspace")
    expected = Path(detail.get("expected_output") or expected_plus_raster(workspace, scenario)).expanduser().resolve()
    require_within(expected, [workspace], "PLUS expected output")
    request = workspace / f"plus_v142_gui_request_{scenario}.json"
    state = workspace / "plus_execution_state.json"
    return scenario, workspace, expected, request, state


def render_value(value: Any, context: dict[str, Any]) -> Any:
    """Render ${field} placeholders from a flat, local request context."""
    if not isinstance(value, str):
        return value
    def replacement(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise GuiAutomationError(f"PLUS GUI profile references unavailable context field: {key}")
        return str(context[key])
    return re.sub(r"\$\{([A-Za-z0-9_.-]+)\}", replacement, value)


def request_context(envelope: dict[str, Any], scenario: str, workspace: Path, expected: Path) -> dict[str, Any]:
    detail = envelope.get("parameters", {}).get("parameters", {})
    detail = detail if isinstance(detail, dict) else {}
    history = [str(item) for item in detail.get("historical_lulc", []) if isinstance(item, str)]
    drivers = detail.get("driver_factors", {}) if isinstance(detail.get("driver_factors"), dict) else {}
    context: dict[str, Any] = {"scenario": scenario, "workspace": str(workspace), "expected_output": str(expected),
                               "historical_lulc_count": len(history)}
    for index, item in enumerate(history):
        context[f"historical_lulc_{index}"] = item
    for key, value in drivers.items():
        if isinstance(value, str):
            context[f"driver_{key}"] = value
    settings = detail.get("plus_settings", {}) if isinstance(detail.get("plus_settings"), dict) else {}
    for key, value in settings.items():
        if isinstance(value, (str, int, float)) or value is None:
            context[f"plus_{key}"] = "" if value is None else value
    resource = detail.get("resource_extraction", {}) if isinstance(detail.get("resource_extraction"), dict) else {}
    for key, value in resource.items():
        if isinstance(value, (str, int, float)) or value is None:
            context[f"re_{key}"] = "" if value is None else value
    return context


def profile_path() -> Path | None:
    local = load_local_paths()
    raw = os.getenv("PLUS_V142_UI_PROFILE") or local.get("plus_v142_ui_profile")
    if not isinstance(raw, str) or not raw.strip() or is_unc(raw):
        return None
    return Path(os.path.expandvars(raw)).expanduser().resolve()


def requires_elevation() -> bool:
    """The pinned official executable requests elevation on this Windows build."""
    value = load_local_paths().get("plus_v142_requires_elevation", True)
    return value is not False


def worker_workspace(envelope: dict[str, Any]) -> Path:
    params = envelope.get("parameters", {})
    if envelope.get("operation") == "plus.calibrate":
        raw = params.get("workspace")
        if not isinstance(raw, str) or not raw or is_unc(raw):
            raise ValueError("official HPSCIL PLUS calibration needs a local workspace")
        workspace = Path(raw).expanduser().resolve()
        allowed = os.getenv("MINING_GIS_MCP_WORKSPACE") or os.getenv("MINING_PLUS_OUTPUT_ROOT") or (ROOT / "outputs" / "mcp")
        return require_within(workspace, [Path(allowed).expanduser().resolve()], "PLUS calibration workspace")
    return scenario_paths(envelope)[1]


def elevated_worker(envelope: dict[str, Any]) -> dict[str, Any]:
    """Run this same local bridge at the PLUS process integrity level via UAC.

    The UAC dialog is intentional: it is the Windows-approved boundary that
    lets pywinauto access the vendor application without weakening UAC or
    exposing any control endpoint over the network.
    """
    workspace = worker_workspace(envelope)
    workspace.mkdir(parents=True, exist_ok=True)
    request_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(envelope.get("request_id") or "plus"))
    request = workspace / f"plus_v142_elevated_request_{request_id}.json"
    reply = workspace / f"plus_v142_elevated_response_{request_id}.json"
    write_json(request, envelope)
    worker = ROOT / "scripts" / "plus_v142_elevated_worker.ps1"
    command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(worker),
               "-Python", sys.executable, "-Bridge", str(Path(__file__).resolve()), "-Request", str(request),
               "-Response", str(reply)]
    try:
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 encoding="utf-8", errors="replace", timeout=180, check=False)
    except subprocess.TimeoutExpired:
        return response(envelope, "waiting_interactive", outputs=[str(request), str(reply)],
                        message="waiting for the local elevated HPSCIL PLUS worker; approve the Windows UAC prompt if it is visible")
    if reply.is_file():
        result = read_json(reply, {})
        if isinstance(result, dict):
            result.setdefault("outputs", [])
            result["outputs"] = [*result["outputs"], str(request), str(reply)]
            return result
    return response(envelope, "failed", outputs=[str(request)],
                    error=process.stderr.strip() or process.stdout.strip() or "elevated HPSCIL PLUS worker did not write a response")


def load_profile(path: Path | None) -> tuple[dict[str, Any], str | None]:
    if path is None or not path.is_file():
        return {}, None
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        raise ValueError("official HPSCIL PLUS GUI profile must be a JSON object")
    if payload.get("profile_version") != "1.0" or payload.get("software") != SOFTWARE_NAME:
        raise ValueError("official HPSCIL PLUS GUI profile has an unsupported profile version or software identity")
    return payload, sha256(path)


def scenario_steps(profile: dict[str, Any], scenario: str) -> list[dict[str, Any]]:
    base = profile.get("steps", [])
    overrides = profile.get("scenario_steps", {})
    extra = overrides.get(scenario, []) if isinstance(overrides, dict) else []
    if not isinstance(base, list) or not isinstance(extra, list):
        raise ValueError("official HPSCIL PLUS GUI profile steps must be lists")
    steps = [item for item in [*base, *extra] if isinstance(item, dict)]
    identifiers = [str(item.get("id", "")).strip() for item in steps]
    if not steps or not all(identifiers) or len(set(identifiers)) != len(identifiers):
        return []
    return steps


class PlusGui:
    """pywinauto-first controller with an OpenCV screenshot fallback."""

    def __init__(self, process_id: int, profile: dict[str, Any], profile_file: Path | None, artifact_dir: Path):
        try:
            from pywinauto import Desktop  # type: ignore
        except ImportError as error:
            raise GuiAutomationError("install the plus-gui extra: python -m pip install -e .\\mcp_server[validation,plus-gui]") from error
        window_spec = profile.get("window", {}) if isinstance(profile.get("window"), dict) else {}
        backend = str(window_spec.get("backend", "uia"))
        criteria: dict[str, Any] = {"process": process_id}
        for key in ("title", "title_re", "class_name", "control_type", "auto_id"):
            if isinstance(window_spec.get(key), str) and window_spec[key]:
                criteria[key] = window_spec[key]
        self.desktop = Desktop(backend=backend)
        self.process_id = process_id
        self.window = self.desktop.window(**criteria)
        self.window.wait("exists visible ready", timeout=float(window_spec.get("timeout_seconds", 20)))
        # Qt's screenshot fallback sees the on-screen composition.  Bring the
        # elevated PLUS window forward before collecting a template or clicking
        # a menu so an unrelated foreground app cannot hide the target.
        self.window.set_focus()
        self.profile_file = profile_file
        self.artifact_dir = artifact_dir
        self.backend = backend

    @staticmethod
    def _uia_criteria(target: dict[str, Any]) -> dict[str, Any]:
        values = target.get("uia", target)
        if not isinstance(values, dict):
            return {}
        allowed = ("title", "title_re", "auto_id", "class_name", "control_type", "best_match", "found_index")
        return {key: value for key, value in values.items() if key in allowed and value not in (None, "")}

    def _control(self, target: dict[str, Any]):
        criteria = self._uia_criteria(target)
        if not criteria:
            raise GuiAutomationError("profile action has no UI Automation selector")
        try:
            return self.window.child_window(**criteria).wrapper_object()
        except Exception as first_error:
            # Qt popup menus and file dialogs can be sibling windows rather
            # than descendants of the main window.
            for candidate in self.desktop.windows(process=self.process_id):
                try:
                    return candidate.child_window(**criteria).wrapper_object()
                except Exception:
                    continue
            raise first_error

    def _image_target(self, target: dict[str, Any]) -> tuple[Path, float]:
        raw = target.get("image") if isinstance(target, dict) else None
        if isinstance(raw, str):
            raw, threshold = {"template": raw}, 0.92
        elif isinstance(raw, dict):
            threshold = float(raw.get("threshold", 0.92))
        else:
            raise GuiAutomationError("no screenshot fallback is configured for this PLUS GUI action")
        template = raw.get("template")
        if not isinstance(template, str) or not template:
            raise GuiAutomationError("screenshot fallback needs image.template")
        root = self.profile_file.parent if self.profile_file else ROOT / "config"
        candidate = (root / template).resolve() if not Path(template).is_absolute() else Path(template).resolve()
        require_within(candidate, [root], "PLUS GUI screenshot template")
        if not candidate.is_file():
            raise GuiAutomationError(f"screenshot template does not exist: {candidate}")
        return candidate, threshold

    def _template_center(self, target: dict[str, Any]) -> tuple[int, int, float]:
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as error:
            raise GuiAutomationError("image fallback needs opencv-python-headless and numpy from the plus-gui extra") from error
        template, threshold = self._image_target(target)
        screenshot = np.asarray(self.window.capture_as_image().convert("RGB"))[:, :, ::-1]
        needle = cv2.imread(str(template), cv2.IMREAD_COLOR)
        if needle is None or needle.shape[0] > screenshot.shape[0] or needle.shape[1] > screenshot.shape[1]:
            raise GuiAutomationError(f"invalid PLUS GUI screenshot template: {template}")
        _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(screenshot, needle, cv2.TM_CCOEFF_NORMED))
        if score < threshold:
            raise GuiAutomationError(f"screenshot template did not meet threshold ({score:.3f} < {threshold:.3f}): {template.name}")
        return point[0] + needle.shape[1] // 2, point[1] + needle.shape[0] // 2, float(score)

    def click(self, target: dict[str, Any]) -> dict[str, Any]:
        try:
            control = self._control(target)
            control.click_input()
            return {"route": "pywinauto", "control": control.window_text()}
        except Exception as selector_error:
            x, y, score = self._template_center(target)
            self.window.click_input(coords=(x, y))
            return {"route": "image", "x": x, "y": y, "score": score, "selector_error": str(selector_error)}

    def set_text(self, target: dict[str, Any], value: str) -> dict[str, Any]:
        try:
            control = self._control(target)
            control.set_focus()
            if hasattr(control, "set_edit_text"):
                control.set_edit_text(value)
            else:
                control.type_keys("^a{BACKSPACE}" + value, with_spaces=True, set_foreground=True)
            return {"route": "pywinauto", "control": control.window_text()}
        except Exception as selector_error:
            self.click(target)
            self.window.type_keys("^a{BACKSPACE}" + value, with_spaces=True, set_foreground=True)
            return {"route": "image", "selector_error": str(selector_error)}

    def select(self, target: dict[str, Any], value: str) -> dict[str, Any]:
        try:
            control = self._control(target)
            control.select(value)
            return {"route": "pywinauto", "control": control.window_text()}
        except Exception as selector_error:
            self.click(target)
            self.window.type_keys(value, with_spaces=True, set_foreground=True)
            self.window.type_keys("{ENTER}")
            return {"route": "image", "selector_error": str(selector_error)}

    def menu(self, step: dict[str, Any]) -> dict[str, Any]:
        path = step.get("path")
        if isinstance(path, str) and path:
            try:
                self.window.menu_select(path)
                return {"route": "pywinauto_menu", "path": path}
            except Exception:
                pass
        target = step.get("target")
        if not isinstance(target, dict):
            raise GuiAutomationError("menu action needs path or target")
        return self.click(target)

    def capture(self, name: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "window"
        output = self.artifact_dir / f"{safe}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        self.window.capture_as_image().save(output)
        return output

    @staticmethod
    def _control_records(window: Any) -> list[dict[str, Any]]:
        controls: list[dict[str, Any]] = []
        for item in window.descendants():
            try:
                rectangle = item.rectangle()
                controls.append({"title": item.window_text(), "automation_id": item.automation_id(),
                                 "control_type": item.element_info.control_type, "class_name": item.class_name(),
                                 "rectangle": [rectangle.left, rectangle.top, rectangle.right, rectangle.bottom]})
            except Exception:
                continue
        return controls

    def calibration(self, label: str = "plus_v142_calibration") -> dict[str, Any]:
        windows: list[dict[str, Any]] = []
        # Qt occasionally exposes the same dialog twice through UI Automation.
        # A calibration report is an inventory, so one record per visible title
        # is clearer than duplicate copies of the identical control tree.
        seen_titles: set[str] = set()
        for index, candidate in enumerate(self.desktop.windows(process=self.process_id)):
            try:
                title = candidate.window_text()
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                safe_title = re.sub(r"[^A-Za-z0-9_.-]+", "_", title).strip("_") or f"window_{index}"
                screenshot = self.artifact_dir / f"{label}_{index}_{safe_title}.png"
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                candidate.capture_as_image().save(screenshot)
                windows.append({"title": title, "screenshot": str(screenshot),
                                "controls": self._control_records(candidate)})
            except Exception:
                continue
        main_controls = self._control_records(self.window)
        main_screenshot = self.capture(label)
        return {"backend": self.backend, "window_title": self.window.window_text(), "screenshot": str(main_screenshot),
                "controls": main_controls, "windows": windows}

    def close_auxiliary_dialogs(self) -> list[str]:
        """Close idle child dialogs before opening another calibration screen."""
        closed: list[str] = []
        main_title = self.window.window_text()
        for candidate in self.desktop.windows(process=self.process_id):
            try:
                title = candidate.window_text()
                if not title or title == main_title or title.lower() in {"progress", "running"}:
                    continue
                candidate.close()
                closed.append(title)
            except Exception:
                continue
        return closed


def execute_steps(gui: PlusGui, steps: list[dict[str, Any]], context: dict[str, Any], completed: list[str],
                  update: Callable[[list[str], str | None], None]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    done = set(completed)
    for step in steps:
        identifier = str(step["id"])
        if identifier in done:
            events.append({"id": identifier, "status": "reused"})
            continue
        action = str(step.get("action", "")).strip().lower()
        target = step.get("target") if isinstance(step.get("target"), dict) else {}
        if action == "click":
            event = gui.click(target)
        elif action == "set_text":
            event = gui.set_text(target, str(render_value(step.get("value", ""), context)))
        elif action == "select":
            event = gui.select(target, str(render_value(step.get("value", ""), context)))
        elif action == "menu":
            event = gui.menu({**step, "path": render_value(step.get("path"), context)})
        elif action == "hotkey":
            gui.window.type_keys(str(render_value(step.get("keys", ""), context)), set_foreground=True)
            event = {"route": "pywinauto", "keys": step.get("keys", "")}
        elif action == "wait":
            seconds = min(float(step.get("seconds", 1)), 30.0)
            if seconds < 0:
                raise GuiAutomationError("wait seconds cannot be negative")
            time.sleep(seconds)
            event = {"seconds": seconds}
        elif action == "capture":
            event = {"screenshot": str(gui.capture(identifier))}
        else:
            raise GuiAutomationError(f"unsupported PLUS GUI profile action: {action}")
        if float(step.get("after_seconds", 0)) > 0:
            time.sleep(min(float(step["after_seconds"]), 30.0))
        completed.append(identifier)
        done.add(identifier)
        update(completed, identifier)
        events.append({"id": identifier, "status": "completed", **event})
    return events


def output_validation(expected: Path, reference: str | None) -> dict[str, Any]:
    if not expected.is_file() or expected.stat().st_size <= 8:
        raise ValueError(f"contracted PLUS output does not exist or is empty: {expected}")
    with expected.open("rb") as stream:
        if stream.read(4) not in {b"II*\x00", b"MM\x00*"}:
            raise ValueError("contracted PLUS output is not a TIFF")
    try:
        import rasterio  # type: ignore
    except ImportError as error:
        raise ValueError("GeoTIFF acceptance needs the validation extra (rasterio)") from error
    with rasterio.open(expected) as raster:
        if raster.count != 1 or not raster.crs or raster.width <= 0 or raster.height <= 0:
            raise ValueError("PLUS output lacks a valid single-band spatial raster contract")
        if not (raster.dtypes[0].startswith("int") or raster.dtypes[0].startswith("uint")):
            raise ValueError("PLUS output must use an integer LULC class raster")
        report: dict[str, Any] = {"status": "completed", "output": str(expected), "width": raster.width,
                                  "height": raster.height, "crs": str(raster.crs), "dtype": raster.dtypes[0],
                                  "transform": list(raster.transform)[:6]}
        if reference and Path(reference).is_file():
            with rasterio.open(reference) as master:
                matches = (master.crs == raster.crs and master.width == raster.width and master.height == raster.height
                           and master.transform.almost_equals(raster.transform))
                report["matches_historical_lulc_grid"] = matches
                if not matches:
                    raise ValueError("PLUS output is not aligned with the latest historical LULC grid")
    report_path = expected.with_suffix(expected.suffix + ".validation.json")
    write_json(report_path, report)
    report["report"] = str(report_path)
    return report


def stable_output(expected: Path) -> bool:
    seconds = max(0.0, float(os.getenv("MINING_PLUS_OUTPUT_STABLE_SECONDS", "5")))
    if not expected.is_file() or expected.stat().st_size <= 8:
        return False
    # See plus_backend.adopt_existing_output: Windows can round mtime forward
    # relative to the process clock, so an apparent negative age is treated as
    # zero rather than incorrectly rejecting a zero-second stability request.
    apparent_age = max(0.0, time.time() - expected.stat().st_mtime)
    return apparent_age >= seconds


def initial_state(scenario: str, expected: Path, identity: dict[str, Any], profile_file: Path | None,
                  profile_digest: str | None) -> dict[str, Any]:
    return {"bridge": BRIDGE_NAME, "software": SOFTWARE_NAME, "scenario": scenario, "status": "prepared",
            "expected_output": str(expected), "executable_identity": identity,
            "profile": str(profile_file) if profile_file else None, "profile_sha256": profile_digest,
            "completed_steps": [], "attempts": 0}


def write_request(envelope: dict[str, Any], identity: dict[str, Any], dry_run: bool) -> tuple[str, Path, Path, Path, dict[str, Any]]:
    scenario, workspace, expected, request, state_path = scenario_paths(envelope)
    workspace.mkdir(parents=True, exist_ok=True)
    profile_file = profile_path()
    profile, digest = load_profile(profile_file)
    state = read_json(state_path, {})
    if not isinstance(state, dict) or state.get("bridge") != BRIDGE_NAME or state.get("scenario") != scenario:
        state = initial_state(scenario, expected, identity, profile_file, digest)
    # Keep the last applied profile hash intact here.  The run method compares
    # it with the requested profile before deciding whether saved GUI steps can
    # safely be reused after an interruption.
    state.update({"expected_output": str(expected), "profile": str(profile_file) if profile_file else None,
                  "requested_profile_sha256": digest, "dry_run": dry_run})
    write_json(request, {"bridge": BRIDGE_NAME, "software": SOFTWARE_NAME, "scenario": scenario,
                         "request": envelope, "expected_output": str(expected), "identity": identity,
                         "profile": str(profile_file) if profile_file else None, "profile_sha256": digest})
    write_json(state_path, state)
    return scenario, workspace, expected, state_path, state


def capabilities(envelope: dict[str, Any]) -> dict[str, Any]:
    installation: dict[str, Any]
    try:
        _, _, installation = configured_installation()
        installed, error = True, None
    except Exception as caught:
        installed, error, installation = False, str(caught), {}
    profile_file = profile_path()
    profile, _ = load_profile(profile_file) if profile_file and profile_file.is_file() else ({}, None)
    return response(envelope, "completed", result={
        "backend": "plus", "software": SOFTWARE_NAME, "mode": "local-gui-automation", "local_only": True,
        "official_remote": OFFICIAL_REMOTE, "pinned_commit": PINNED_COMMIT, "pinned_executable_sha256": PINNED_SHA256,
        "installation_verified": installed, "installation_error": error, "executable_identity": installation,
        "pywinauto_available": importlib.util.find_spec("pywinauto") is not None,
        "image_fallback_available": importlib.util.find_spec("cv2") is not None,
        "profile": str(profile_file) if profile_file else None,
        "profile_calibrated": bool(profile.get("calibrated") is True and scenario_steps(profile, "ND")),
        "operations": ["system.capabilities", "plus.calibrate", "plus.run_scenario"],
        "limitations": ["The first run needs a local, version-specific UI calibration profile.",
                        "completed is returned only after the contracted GeoTIFF is written and passes grid checks."],
    })


def calibrate(envelope: dict[str, Any]) -> dict[str, Any]:
    """Open the local window once and save selectors/screenshots without a model run."""
    _, executable, identity = configured_installation()
    params = envelope.get("parameters", {})
    raw_workspace = params.get("workspace")
    if not isinstance(raw_workspace, str) or not raw_workspace or is_unc(raw_workspace):
        raise ValueError("official HPSCIL PLUS calibration needs a local workspace")
    workspace = Path(raw_workspace).expanduser().resolve()
    allowed = os.getenv("MINING_GIS_MCP_WORKSPACE") or os.getenv("MINING_PLUS_OUTPUT_ROOT") or (ROOT / "outputs" / "mcp")
    require_within(workspace, [Path(allowed).expanduser().resolve()], "PLUS calibration workspace")
    profile_file = profile_path()
    profile, _ = load_profile(profile_file)
    open_menu = params.get("open_menu")
    if open_menu is not None and (not isinstance(open_menu, str) or not open_menu.strip()):
        raise ValueError("open_menu must be a non-empty visible PLUS menu title")
    open_menu_item = params.get("open_menu_item")
    if open_menu_item is not None and (not isinstance(open_menu_item, str) or not open_menu_item.strip()):
        raise ValueError("open_menu_item must be a non-empty PLUS command title")
    if open_menu_item is not None and open_menu is None:
        raise ValueError("open_menu_item requires open_menu")
    close_dialogs = params.get("close_auxiliary_dialogs", False)
    if not isinstance(close_dialogs, bool):
        raise ValueError("close_auxiliary_dialogs must be a boolean")
    supplied_pid = params.get("process_id")
    if pid_is_alive(supplied_pid):
        process_id, launch_mode = int(supplied_pid), "attached_existing_gui"
    else:
        process = subprocess.Popen([str(executable)], cwd=str(executable.parent), shell=False)
        process_id, launch_mode = process.pid, "launched_gui"
        time.sleep(min(float(profile.get("startup_wait_seconds", 2)) if profile else 2, 15))
    artifact_dir = workspace / "plus_v142_gui_artifacts"
    closed_dialogs: list[str] = []
    try:
        gui = PlusGui(process_id, profile, profile_file, artifact_dir)
        if close_dialogs:
            closed_dialogs = gui.close_auxiliary_dialogs()
            time.sleep(0.3)
        if isinstance(open_menu, str):
            gui.click({"uia": {"title": open_menu, "control_type": "MenuItem"}})
            time.sleep(0.3)
        if isinstance(open_menu_item, str):
            gui.click({"uia": {"title": open_menu_item, "control_type": "MenuItem"}})
            time.sleep(0.5)
        label = "plus_v142_calibration"
        if isinstance(open_menu, str):
            label = "plus_v142_menu_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", open_menu)
        if isinstance(open_menu_item, str):
            label += "_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", open_menu_item)
        report = gui.calibration(label)
    except Exception as caught:
        report = {"error": str(caught), "process_id": process_id}
    report.update({"bridge": BRIDGE_NAME, "software": SOFTWARE_NAME, "identity": identity,
                   "process_id": process_id, "launch_mode": launch_mode, "opened_menu": open_menu,
                   "opened_menu_item": open_menu_item, "closed_auxiliary_dialogs": closed_dialogs})
    suffix = "" if not isinstance(open_menu, str) else "_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", open_menu)
    if isinstance(open_menu_item, str):
        suffix += "_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", open_menu_item)
    report_path = artifact_dir / f"plus_v142_calibration{suffix}.json"
    write_json(report_path, report)
    return response(envelope, "waiting_interactive", outputs=[str(report_path)], process_id=process_id,
                    message="official HPSCIL PLUS calibration report was written; update the local UI profile, then resume or close the window")


def run_scenario(envelope: dict[str, Any]) -> dict[str, Any]:
    _, executable, identity = configured_installation()
    dry_run = bool(envelope.get("parameters", {}).get("dry_run", False))
    scenario, workspace, expected, state_path, state = write_request(envelope, identity, dry_run)
    detail = envelope.get("parameters", {}).get("parameters", {})
    detail = detail if isinstance(detail, dict) else {}
    history = [item for item in detail.get("historical_lulc", []) if isinstance(item, str)]
    if stable_output(expected):
        validation = output_validation(expected, history[-1] if history else None)
        state.update({"status": "completed", "validation": validation, "completed_at": time.time()})
        write_json(state_path, state)
        return response(envelope, "completed", outputs=[str(expected), validation["report"]],
                        result={"landuse_raster": str(expected), "validation": validation},
                        message="existing contracted HPSCIL PLUS output passed validation")
    if dry_run:
        return response(envelope, "prepared", outputs=[str(workspace / f"plus_v142_gui_request_{scenario}.json"), str(state_path)],
                        message="official HPSCIL PLUS request and per-scenario GUI state prepared (dry run)")
    profile_file = profile_path()
    profile, digest = load_profile(profile_file)
    previous_pid = state.get("process_id")
    same_profile = state.get("profile_sha256") == digest
    if pid_is_alive(previous_pid) and not same_profile:
        state.update({"status": "waiting_interactive", "reason": "ui_profile_changed_while_gui_running",
                      "process_id": previous_pid, "updated_at": time.time()})
        write_json(state_path, state)
        return response(envelope, "waiting_interactive", outputs=[str(state_path)], process_id=previous_pid,
                        message="the official HPSCIL PLUS GUI profile changed during a live session; close that window before resuming so the full calibrated sequence can be replayed")
    process_id: int
    if pid_is_alive(previous_pid):
        process_id = int(previous_pid)
        state["resume_mode"] = "attached_existing_gui"
    else:
        process = subprocess.Popen([str(executable)], cwd=str(executable.parent), shell=False)
        process_id = process.pid
        state.update({"process_id": process_id, "attempts": int(state.get("attempts", 0)) + 1,
                      # A restarted desktop application has no reliable UI state.
                      # Reapply the calibrated sequence instead of skipping saved
                      # steps that were completed in a now-closed window.
                      "resume_mode": "restarted_gui", "completed_steps": []})
        time.sleep(min(float(profile.get("startup_wait_seconds", 2)) if profile else 2, 15))
    artifact_dir = workspace / "plus_v142_gui_artifacts"
    state.update({"status": "running", "process_id": process_id, "profile_sha256": digest, "updated_at": time.time()})
    write_json(state_path, state)
    try:
        gui = PlusGui(process_id, profile, profile_file, artifact_dir)
        steps = scenario_steps(profile, scenario) if profile.get("calibrated") is True else []
        if not steps:
            calibration = gui.calibration()
            calibration_path = artifact_dir / "plus_v142_calibration.json"
            write_json(calibration_path, calibration)
            state.update({"status": "waiting_interactive", "reason": "ui_profile_not_calibrated",
                          "calibration": str(calibration_path), "process_id": process_id})
            write_json(state_path, state)
            return response(envelope, "waiting_interactive", outputs=[str(state_path), str(calibration_path), calibration["screenshot"]],
                            process_id=process_id, message="HPSCIL PLUS window is ready; calibrate config/plus_v142_ui_profile.json from the saved local control report, then resume")
        completed = list(state.get("completed_steps", [])) if same_profile else []
        def persist(done: list[str], current: str | None) -> None:
            state.update({"status": "running", "process_id": process_id, "completed_steps": done,
                          "current_step": current, "updated_at": time.time()})
            write_json(state_path, state)
        events = execute_steps(gui, steps, request_context(envelope, scenario, workspace, expected), completed, persist)
        screenshot = gui.capture("plus_v142_after_automation")
        state.update({"completed_steps": completed, "automation_events": events, "screenshot": str(screenshot)})
    except Exception as caught:
        state.update({"status": "waiting_interactive", "reason": "gui_automation_needs_calibration", "error": str(caught),
                      "process_id": process_id, "updated_at": time.time()})
        write_json(state_path, state)
        return response(envelope, "waiting_interactive", outputs=[str(state_path)], process_id=process_id,
                        message=f"HPSCIL PLUS GUI needs local calibration or attention: {caught}")
    if stable_output(expected):
        validation = output_validation(expected, history[-1] if history else None)
        state.update({"status": "completed", "validation": validation, "completed_at": time.time()})
        write_json(state_path, state)
        return response(envelope, "completed", outputs=[str(expected), validation["report"]],
                        result={"landuse_raster": str(expected), "validation": validation},
                        message="HPSCIL PLUS GUI automation produced and validated the contracted output")
    state.update({"status": "waiting_interactive", "reason": "awaiting_contracted_output", "updated_at": time.time()})
    write_json(state_path, state)
    return response(envelope, "waiting_interactive", outputs=[str(state_path)], process_id=process_id,
                    message="HPSCIL PLUS GUI steps were submitted; resume after the contracted GeoTIFF is available")


def handle(envelope: dict[str, Any], *, elevated: bool) -> dict[str, Any]:
    if envelope.get("protocol_version") != "1.0":
        return response(envelope, "failed", error="unsupported protocol version")
    operation = envelope.get("operation")
    dry_run = bool(envelope.get("parameters", {}).get("dry_run", False))
    if (not elevated and requires_elevation() and operation in {"plus.calibrate", "plus.run_scenario"}
            and not (operation == "plus.run_scenario" and dry_run)):
        return elevated_worker(envelope)
    if operation == "system.capabilities":
        return capabilities(envelope)
    if operation == "plus.calibrate":
        return calibrate(envelope)
    if operation == "plus.run_scenario":
        return run_scenario(envelope)
    return response(envelope, "failed", error=f"unsupported PLUS operation: {operation}")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--elevated-request", type=Path)
    parser.add_argument("--elevated-response", type=Path)
    args, _ = parser.parse_known_args()
    envelope: dict[str, Any] = {}
    try:
        if bool(args.elevated_request) != bool(args.elevated_response):
            raise ValueError("elevated PLUS worker needs both request and response paths")
        elevated = bool(args.elevated_request)
        envelope = read_json(args.elevated_request, {}) if elevated else json.load(sys.stdin)
        if not isinstance(envelope, dict):
            raise ValueError("PLUS bridge request must be a JSON object")
        result = handle(envelope, elevated=elevated)
        if elevated:
            write_json(args.elevated_response, result)
    except Exception as caught:
        result = response(envelope, "failed", error=str(caught))
        if args.elevated_response:
            write_json(args.elevated_response, result)
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
