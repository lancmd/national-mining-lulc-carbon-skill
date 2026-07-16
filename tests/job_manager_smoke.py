"""Exercise submit/status/output handling without invoking external GIS software."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from job_manager import outputs, status, submit  # noqa: E402


workspace = ROOT / "outputs" / "job_manager_smoke"
workspace.mkdir(parents=True, exist_ok=True)
job = workspace / "workflow_job.json"
job.write_text(json.dumps({
    "schema_version": 1, "project_id": "job-manager-smoke", "workspace": str(workspace),
    "security": {"input_roots": [str(ROOT)], "output_root": str(workspace), "confirm_overwrite": False},
    "software": {}, "stages": [],
}), encoding="utf-8")
record = submit(job)
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    current = status(record["job_id"])
    if current["status"] != "running":
        break
    time.sleep(0.1)
assert current["status"] == "completed", current
listed = outputs(record["job_id"])
assert listed["status"] == "completed"
print(json.dumps({"status": "completed", "job_id": record["job_id"], "progress": current["progress"]}))
