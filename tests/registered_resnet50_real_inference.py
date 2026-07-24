"""Opt-in local integration test using the real registered ResNet-50 package.

Set MAESA_RUN_REGISTERED_RESNET50=1 together with model and raster paths. The
test is intentionally skipped in portable CI because model weights and research
imagery are local user data, not repository fixtures.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pytorch_patch_lulc import infer_patch_grid, validate_native_package  # noqa: E402


if os.getenv("MAESA_RUN_REGISTERED_RESNET50") != "1":
    print(json.dumps({"status": "completed", "execution": "skipped", "reason": "set MAESA_RUN_REGISTERED_RESNET50=1 for local real-model inference"}))
    raise SystemExit(0)

package = Path(os.environ["MAESA_RESNET50_MODEL_PACKAGE"]).expanduser().resolve()
raster = Path(os.environ["MAESA_RESNET50_TEST_RASTER"]).expanduser().resolve()
audit = validate_native_package(package)
assert audit["status"] == "valid" and audit["registry_hash_pinned"], audit
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    report = infer_patch_grid(package, raster, root / "lulc_patch_grid.tif", root / "confidence.tif",
                              patch_size=int(os.getenv("MAESA_RESNET50_PATCH_SIZE", "256")),
                              stride=int(os.getenv("MAESA_RESNET50_PATCH_STRIDE", "256")),
                              band_indexes=[int(item) for item in os.getenv("MAESA_RESNET50_BAND_INDEXES", "1,2,3").split(",")],
                              input_scale=float(os.getenv("MAESA_RESNET50_INPUT_SCALE", "1.0")), batch_size=1)
    assert Path(report["class_output"]).is_file() and Path(report["confidence_output"]).is_file(), report
    import rasterio
    with rasterio.open(report["class_output"]) as source:
        assert set(int(value) for value in source.read(1).ravel()).issubset(set(range(0, 7))), report
print(json.dumps({"status": "completed", "execution": "real_registered_resnet50", "model": audit["registered_model_id"]}, ensure_ascii=False))
