"""Validate local-first LLM Copilot configuration without contacting a model."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
print(json.dumps({"status": "completed", "checks": ["LLM provider config", "local-first endpoint guard"]}))
