"""Ensure project construction returns the validator result in the same MCP response."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    image, roi = root / "image.tif", root / "roi.gpkg"
    image.write_bytes(b"fixture")
    roi.write_bytes(b"fixture")
    envelope = {"operation": "project.build_from_inputs", "parameters": {
        "output_project": str(root / "project.json"), "project_id": "backend-validation", "workspace": "runtime",
        "task_type": "classification_only", "imagery_periods": [{"year": 2025, "path": str(image)}],
        "training_roi": str(roi),
    }}
    process = subprocess.run([sys.executable, str(ROOT / "scripts" / "project_backend.py")], input=json.dumps(envelope),
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    assert process.returncode == 0, process.stdout
    result = json.loads(process.stdout)
    assert result["status"] == "completed", result
    assert result["result"]["project_validation"]["status"] == "valid", result

print('{"status":"completed","checks":["build invokes full project validation"]}')
