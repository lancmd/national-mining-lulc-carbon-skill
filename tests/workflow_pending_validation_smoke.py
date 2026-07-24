"""A successful validator process must preserve the validation-paused workflow state."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from workflow_agent import JobRunner, reported_status  # noqa: E402


assert reported_status(json.dumps({"status": "pending_validation", "sections": {"lulc": {"status": "completed"}}}, indent=2)) == "pending_validation"


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    source = root / "input.txt"; source.write_text("input", encoding="utf-8")
    workspace = root / "runtime"; report = workspace / "validation" / "report.json"
    program = ("import json; from pathlib import Path; Path('validation').mkdir(exist_ok=True); "
               "Path('validation/report.json').write_text('{}'); print(json.dumps({'status':'pending_validation'}, indent=2))")
    job = {"schema_version": 1, "project_id": "validation-status", "workspace": str(workspace),
           "security": {"input_roots": [str(root)], "output_root": str(workspace)}, "software": {}, "stages": [{
               "id": "analysis_validation", "adapter": "command", "enabled": True,
               "command": [sys.executable, "-c", program], "inputs": [str(source)], "outputs": [str(report)], "depends_on": [],
           }]}
    job_path = root / "job.json"; job_path.write_text(json.dumps(job), encoding="utf-8")
    runner = JobRunner(job_path)
    assert runner.run() == 0
    state = json.loads(runner.state_path.read_text(encoding="utf-8"))
    assert state["stages"]["analysis_validation"]["status"] == "pending_validation", state
    assert state["workflow"]["status"] == "paused", state

print('{"status":"completed","checks":["validation status propagation"]}')
