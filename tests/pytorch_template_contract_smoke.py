"""Keep the shipped PyTorch template aligned with the inference input contract."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
template = json.loads((ROOT / "templates" / "pytorch_model_config.json").read_text(encoding="utf-8"))
assert "sensor" not in template and "spatial_resolution_m" not in template
input_config = template["input"]
for key in ("sensor", "resolution_m", "value_range", "scale", "bands", "band_indexes", "mean", "std"):
    assert key in input_config, key
assert input_config["value_range"] == [0, 10000]
print('{"status":"completed","checks":["PyTorch template input fields"]}')
