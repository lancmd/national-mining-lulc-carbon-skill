"""Exercise the portable PLUS V1.4.2 GUI-profile contract without launching a GUI."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from plus_v142_gui_bridge import PINNED_COMMIT, PINNED_EXECUTABLE, PINNED_SHA256, render_value, scenario_steps  # noqa: E402


profile = {
    "calibrated": True,
    "steps": [{"id": "open_plus", "action": "click"}],
    "scenario_steps": {"RE": [{"id": "load_subsidence", "action": "set_text"}]},
}
assert [step["id"] for step in scenario_steps(profile, "ND")] == ["open_plus"]
assert [step["id"] for step in scenario_steps(profile, "RE")] == ["open_plus", "load_subsidence"]
assert scenario_steps({"calibrated": True, "steps": [{"id": "dup"}, {"id": "dup"}]}, "ND") == []
assert render_value("${scenario}:${driver_dem}:${re_core_driver_input}", {
    "scenario": "RE", "driver_dem": "dem_30m.tif", "re_core_driver_input": "subsidence_30m.tif",
}) == "RE:dem_30m.tif:subsidence_30m.tif"
assert PINNED_COMMIT == "de7ba6efd35b530da6c37e81103276a17716602c"
assert PINNED_EXECUTABLE == "PLUS V1.4.2.exe" and len(PINNED_SHA256) == 64

print('{"status":"completed","checks":["PLUS V1.4.2 profile routing","context rendering","pinned official identity"]}')
