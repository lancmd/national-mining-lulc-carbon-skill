"""Validate local-first LLM Copilot configuration without contacting a model."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from maesa_copilot import controlled_plan, validate_execution_plan  # noqa: E402
with tempfile.TemporaryDirectory() as temporary:
    provider = Path(temporary) / "provider.json"
    provider.write_text(json.dumps({"provider": "ollama", "base_url": "http://127.0.0.1:11434", "model": "qwen2.5:7b-instruct",
                                    "allow_cloud": False}), encoding="utf-8")
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "maesa_copilot.py"), "--provider", str(provider),
                              "--message", "检查我的输入", "--dry-run"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", check=False)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["status"] == "prepared" and result["endpoint_is_local"] is True, result
project = ROOT / "tests" / "fixtures" / "local_project" / "project.json"
plan = controlled_plan(project, "validate local workflow")
assert validate_execution_plan(plan, project)["status"] == "valid"
plan["steps"][0]["tool"] = "run_shell_command"
assert validate_execution_plan(plan, project)["status"] == "invalid"
print(json.dumps({"status": "completed", "checks": ["LLM provider config", "local-first endpoint guard", "confirmation-gated plan"]}))
