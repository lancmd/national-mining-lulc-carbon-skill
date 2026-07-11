#!/usr/bin/env python3
"""Local command backend for ecosystem-service scoring."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ecosystem_service import evaluate  # noqa: E402


def main() -> int:
    envelope = json.load(sys.stdin)
    if envelope.get("operation") == "system.capabilities":
        result = {"status": "completed", "result": {"backend": "ecosystem", "operations": ["system.capabilities", "ecosystem.evaluate"]}}
    elif envelope.get("operation") == "ecosystem.evaluate":
        params = envelope["parameters"]
        report = evaluate(Path(params["criteria_table"]).expanduser().resolve(),
                          Path(params["config"]).expanduser().resolve(), Path(params["output"]).expanduser().resolve())
        result = {"status": "completed", "result": report, "outputs": [report["output"]]}
    else:
        result = {"status": "failed", "error": "unsupported ecosystem operation"}
    result.update({"protocol_version": "1.0", "request_id": envelope.get("request_id")})
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
