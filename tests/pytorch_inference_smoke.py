"""Create a tiny exported segmentation model and verify real tiled GeoTIFF inference."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pytorch_lulc import infer  # noqa: E402


class TinySegmentation(torch.nn.Module):
    def forward(self, image: torch.Tensor) -> torch.Tensor:
        signal = image[:, 0:1]
        return torch.cat((signal, -signal), dim=1)


workspace = ROOT / "outputs" / "pytorch_smoke"
if workspace.exists():
    shutil.rmtree(workspace)
package = workspace / "model_package"
package.mkdir(parents=True)
model_path = package / "model.pt2"
program = torch.export.export(TinySegmentation().eval(), (torch.zeros(1, 2, 32, 32),))
ascii_model_dir = Path(tempfile.mkdtemp(prefix="pytorch_export_smoke_"))
try:
    ascii_model = ascii_model_dir / "model.pt2"
    torch.export.save(program, ascii_model)
    shutil.copy2(ascii_model, model_path)
finally:
    shutil.rmtree(ascii_model_dir, ignore_errors=True)
digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
config = {
    "schema_version": 1,
    "model_id": "tiny-segmentation-smoke",
    "format": "exported_program",
    "weights": "model.pt2",
    "sha256": digest,
    "classes": [{"id": 1, "name": "positive"}, {"id": 2, "name": "negative"}],
    "input": {
        "sensor": "synthetic", "resolution_m": 10, "value_range": [-3.0, 3.0],
        "bands": ["signal", "unused"], "band_indexes": [1, 2],
        "mean": [0.0, 0.0], "std": [1.0, 1.0], "scale": 1.0, "offset": 0.0,
        "patch_size": 32, "stride": 24,
    },
    "output": {"type": "logits", "tensor_index": 0, "tensor_key": None,
               "class_nodata": 0, "confidence_nodata": -9999.0},
    "training": {"regions": ["synthetic"], "imagery_years": [2026],
                 "validation_summary": "pipeline smoke test"},
}
(package / "model_config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

input_path = workspace / "input.tif"
data = np.zeros((2, 64, 64), dtype="float32")
data[0, :, :32] = 2.0
data[0, :, 32:] = -2.0
with rasterio.open(input_path, "w", driver="GTiff", width=64, height=64, count=2,
                   dtype="float32", crs="EPSG:32650", transform=from_origin(500000, 3700000, 10, 10)) as sink:
    sink.write(data)

class_path = workspace / "lulc.tif"
confidence_path = workspace / "confidence.tif"
report = infer(package, input_path, class_path, confidence_path, "cpu")
with rasterio.open(class_path) as source:
    classes = source.read(1)
    assert source.crs.to_epsg() == 32650
with rasterio.open(confidence_path) as source:
    confidence = source.read(1)
assert np.all(classes[:, :31] == 1)
assert np.all(classes[:, 33:] == 2)
assert float(confidence.min()) > 0.5
print(json.dumps({"report": report, "class_values": np.unique(classes).tolist(),
                  "confidence_min": float(confidence.min())}, ensure_ascii=False))
