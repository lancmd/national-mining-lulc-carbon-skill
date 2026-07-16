"""Exercise the local ENVI command bridge without requiring ENVI in CI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def call(operation: str, parameters: dict[str, object]) -> dict[str, object]:
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "envi_backend.py")],
                             input=json.dumps({"protocol_version": "1.0", "operation": operation,
                                               "parameters": parameters}),
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             encoding="utf-8", check=False)
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


capability = call("system.capabilities", {})
assert capability["status"] == "completed", capability
assert capability["result"]["mode"] == "local-command", capability
assert capability["result"]["local_only"] is True, capability
assert set(capability["result"]["methods"]) == {"maximum_likelihood", "minimum_distance"}, capability
invalid = call("envi.supervised_classification", {"method": "random_forest"})
assert invalid["status"] == "failed" and "unsupported ENVI method" in invalid["error"], invalid
print(json.dumps({"status": "completed", "checks": ["local ENVI command bridge", "method contract"]}))
