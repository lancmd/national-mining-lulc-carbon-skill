"""Opt-in acceptance test for one calibrated local full-chain project.

The repository cannot include a mine boundary, licensed software session, or
research imagery.  A workstation owner enables this test only after selecting
an approved local project and calibrating PLUS/ArcGIS layouts.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_validator import validate  # noqa: E402
from project_workflow import compile_workflow  # noqa: E402
from workflow_agent import JobRunner  # noqa: E402


if os.getenv("MAESA_RUN_LOCAL_FULL_CHAIN") != "1":
    print(json.dumps({"status": "completed", "execution": "skipped", "reason": "set MAESA_RUN_LOCAL_FULL_CHAIN=1 for a calibrated local acceptance run"}))
    raise SystemExit(0)

raw_project = os.getenv("MAESA_LOCAL_FULL_CHAIN_PROJECT")
if not raw_project:
    raise SystemExit("MAESA_LOCAL_FULL_CHAIN_PROJECT is required when MAESA_RUN_LOCAL_FULL_CHAIN=1")
project = Path(raw_project).expanduser().resolve()
report = validate(project)
assert report["status"] == "valid", report
compiled = compile_workflow(project)
runner = JobRunner(Path(compiled["workflow_job"]), confirm_overwrite=bool(os.getenv("MAESA_LOCAL_FULL_CHAIN_CONFIRM_OVERWRITE") == "1"))
assert runner.run() == 0
state = json.loads(runner.state_path.read_text(encoding="utf-8"))
assert state.get("workflow", {}).get("status") == "completed", state
for name in ("outputs_manifest.json", "provenance.json", "validation_summary.json"):
    assert (runner.workspace / name).is_file(), name
final = state.get("stages", {}).get("analysis_validation", {})
assert final.get("status") == "completed", final
print(json.dumps({"status": "completed", "project": str(project), "workspace": str(runner.workspace)}, ensure_ascii=False))
