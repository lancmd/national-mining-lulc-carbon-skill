"""A generic PLUS request receipt must not overwrite GUI resume state."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from plus_backend import write_request_pack  # noqa: E402


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    workspace = root / "outputs" / "plus" / "ND"
    workspace.mkdir(parents=True)
    execution_state = workspace / "plus_execution_state.json"
    original = {"bridge": "plus_v142_gui_automation", "status": "waiting_interactive", "process_id": os.getpid()}
    execution_state.write_text(json.dumps(original), encoding="utf-8")
    envelope = {"protocol_version": "1.0", "request_id": "state_isolation", "operation": "plus.run_scenario",
                "parameters": {"scenario": "ND", "workspace": str(workspace), "parameters": {
                    "output_directory": str(workspace), "expected_output": str(workspace / "PLUS_ND.tif")}}}
    os.environ["MINING_PLUS_OUTPUT_ROOT"] = str(root)
    _, receipt = write_request_pack(envelope)
    assert Path(receipt).name == "plus_backend_request_state.json"
    assert json.loads(execution_state.read_text(encoding="utf-8")) == original
    os.environ.pop("MINING_PLUS_OUTPUT_ROOT", None)

print('{"status":"completed","checks":["PLUS bridge request receipt","GUI resume state isolation"]}')
