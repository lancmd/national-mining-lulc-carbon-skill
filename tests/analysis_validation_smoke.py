"""Check that the unified analysis-evidence validator accepts a complete report."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analysis_validation import validate_invest, validate_results  # noqa: E402


source = ROOT / "tests" / "fixtures" / "analysis_validation.json"
output = ROOT / "outputs" / "analysis_validation_smoke.json"
report = validate_results(source, output)
assert report["status"] == "completed", report
assert output.exists()
invest = {"workflow_total_t_c": 10.0, "independent_total_t_c": 10.0,
          "models": {"annual_water_yield": {"scenarios": {
              "2020": {"status": "completed", "outputs": ["wyield_2020.tif"], "units": {"water_yield_m3": "m3"}},
              "ND": {"status": "completed", "outputs": ["wyield_nd.tif"], "units": {"water_yield_m3": "m3"}},
          }}}}
assert validate_invest(invest)["status"] == "completed"
invest["models"]["annual_water_yield"]["scenarios"]["ND"]["status"] = "pending_validation"
assert validate_invest(invest)["status"] == "failed"
print(json.dumps({"status": report["status"], "output": report["output"]}, ensure_ascii=False))
