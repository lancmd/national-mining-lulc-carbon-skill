"""Exercise per-scenario PLUS request packs and local-output adoption."""

from __future__ import annotations

import tempfile
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from plus_backend import adopt_existing_output, normalize_bridge_result, write_request_pack  # noqa: E402


def envelope(workspace: Path, scenario: str) -> dict[str, object]:
    output = workspace / f"PLUS_{scenario}.tif"
    return {"protocol_version": "1.0", "request_id": f"plus_{scenario}", "operation": "plus.run_scenario",
            "parameters": {"scenario": scenario, "workspace": str(workspace), "parameters": {
                "output_directory": str(workspace), "expected_output": str(output)}}}


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    prior_output_root = os.environ.get("MINING_PLUS_OUTPUT_ROOT")
    prior_stability = os.environ.get("MINING_PLUS_OUTPUT_STABLE_SECONDS")
    try:
        os.environ["MINING_PLUS_OUTPUT_ROOT"] = str(root)
        # File-age checks protect actual PLUS output handover.  This contract
        # test is about scenario isolation and valid-output adoption, so it
        # explicitly disables the wall-clock wait instead of relying on a
        # Windows runner's timestamp precision.
        os.environ["MINING_PLUS_OUTPUT_STABLE_SECONDS"] = "0"
        nd = envelope(root / "ND", "ND")
        re = envelope(root / "RE", "RE")
        nd_pack, _ = write_request_pack(nd)
        re_pack, _ = write_request_pack(re)
        assert Path(nd_pack).name == "plus_local_request_ND.json"
        assert Path(re_pack).name == "plus_local_request_RE.json"
        assert Path(nd_pack) != Path(re_pack)
        output = root / "ND" / "PLUS_ND.tif"
        output.write_bytes(b"II*\x00local plus output")
        result = adopt_existing_output(nd)
        assert result and result["status"] == "completed" and result["outputs"] == [str(output)], result
        bridge_result = normalize_bridge_result(nd, {"status": "completed", "outputs": [str(output)]})
        assert bridge_result["status"] == "completed" and bridge_result["outputs"] == [str(output)], bridge_result
    finally:
        if prior_output_root is None:
            os.environ.pop("MINING_PLUS_OUTPUT_ROOT", None)
        else:
            os.environ["MINING_PLUS_OUTPUT_ROOT"] = prior_output_root
        if prior_stability is None:
            os.environ.pop("MINING_PLUS_OUTPUT_STABLE_SECONDS", None)
        else:
            os.environ["MINING_PLUS_OUTPUT_STABLE_SECONDS"] = prior_stability
print('{"status":"completed","checks":["independent packs","local output takeover"]}')
