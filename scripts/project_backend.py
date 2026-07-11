#!/usr/bin/env python3
"""Local command backend for local-project validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_validator import validate  # noqa: E402


def main() -> int:
    envelope = json.load(sys.stdin)
    if envelope.get("operation") == "system.capabilities":
        result = {"status": "completed", "result": {"backend": "project", "operations": ["system.capabilities", "project.validate"]}}
    elif envelope.get("operation") == "project.validate":
        report = validate(Path(envelope["parameters"]["project_file"]).expanduser().resolve())
        result = {"status": "completed" if report["status"] == "valid" else "failed", "result": report,
                  "error": None if report["status"] == "valid" else "; ".join(report["errors"])}
    else:
        result = {"status": "failed", "error": "unsupported project operation"}
    result.update({"protocol_version": "1.0", "request_id": envelope.get("request_id")})
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
