"""Ensure public software-control endpoints cannot be enabled through the registry."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))
from mining_mcp_server import BackendRegistry, guard_paths  # noqa: E402
from path_safety import PathSafetyError  # noqa: E402


with tempfile.TemporaryDirectory() as temp:
    registry_path = Path(temp) / "backends.json"
    registry_path.write_text(json.dumps({"protocol_version": "1.0", "backends": {
        "remote": {"transport": "http", "url": "https://example.invalid/commands", "capabilities": []}
    }}), encoding="utf-8")
    result = BackendRegistry(str(registry_path)).call("remote", "system.capabilities", {})
    assert result["status"] == "failed"
    assert "remote software control is disabled" in result["error"]
try:
    guard_paths({"accuracy_config": {"validation_samples": r"\\server\share\samples.csv"}})
    raise AssertionError("nested validation samples escaped the local input policy")
except PathSafetyError:
    pass
print(json.dumps({"status": "completed", "policy": "local-first"}))
