"""Confirm final layouts can reference earlier declared workflow outputs."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_workflow import map_layer_definition  # noqa: E402
from workflow_agent import JobRunner  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary); workspace = root / "runtime"
    output = workspace / "outputs" / "invest" / "carbon.tif"
    stages = {"invest_carbon_ND": {"id": "invest_carbon_ND", "outputs": [str(output)]}}
    layer, dependency = map_layer_definition({"source": "stage_output", "stage_id": "invest_carbon_ND", "output_index": 0,
                                               "name": "ND carbon", "kind": "continuous"}, root, workspace, stages)
    assert layer["path"] == str(output) and dependency == "invest_carbon_ND"
    job = {"schema_version": 1, "project_id": "map-smoke", "workspace": str(workspace),
           "security": {"input_roots": [str(root)], "output_root": str(workspace)},
           "stages": [{"id": "invest_carbon_ND", "adapter": "command", "enabled": True, "outputs": [str(output)]},
                      {"id": "map_layout", "adapter": "arcgis", "enabled": True, "inputs": [str(output)],
                       "outputs": [str(workspace / "outputs" / "map.png")], "depends_on": ["invest_carbon_ND"]}]}
    job_path = root / "job.json"; job_path.write_text(__import__("json").dumps(job), encoding="utf-8")
    runner = JobRunner(job_path, dry_run=True)
    errors = runner.validate_stage(job["stages"][1])
    assert not any("missing or disallowed input" in item for item in errors), errors

print('{"status":"completed","checks":["stage output mapping contract"]}')
