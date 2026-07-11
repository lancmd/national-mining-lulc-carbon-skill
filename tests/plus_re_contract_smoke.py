"""Verify the four default PLUS scenarios and the RE external-PIM input contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_validator import validate  # noqa: E402


def main() -> int:
    project_file = ROOT / "tests" / "fixtures" / "local_project" / "plus_project.json"
    report = validate(project_file)
    if report["status"] != "valid":
        raise AssertionError(report)
    project = json.loads(project_file.read_text(encoding="utf-8"))
    scenarios = project["plus"]["scenarios"]
    if scenarios != ["ND", "UD", "EP", "RE"]:
        raise AssertionError(f"unexpected PLUS defaults: {scenarios}")
    resource = project["plus"]["resource_extraction"]
    if resource["core_driver"] != "subsidence_depth":
        raise AssertionError("RE core driver must be subsidence depth")
    print(json.dumps({"status": "passed", "scenarios": scenarios, "core_driver": resource["core_driver"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
