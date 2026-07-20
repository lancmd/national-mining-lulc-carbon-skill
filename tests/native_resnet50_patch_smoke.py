"""Validate and compile the supported ResNet-50 patch-classifier package shape."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from project_validator import validate  # noqa: E402
from project_builder import build  # noqa: E402
from project_workflow import compile_workflow  # noqa: E402
from pytorch_patch_lulc import EXPECTED_CLASS_NAMES, validate_native_package  # noqa: E402


registered = json.loads((ROOT / "deep_learning" / "registered_models" / "lulc_resnet50_8class.json").read_text(encoding="utf-8"))
assert registered["model_id"] == "lulc-resnet50-8class"
assert [item["standard_6class_lucode"] for item in registered["native_classes"]] == [6, 3, 4, 5, 2, 2, 2, 1]

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    package = root / "resnet50_package"
    weights = package / "model" / "best_resnet50.pth"
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"native-resnet50-test-weights")
    manifest = {
        "name": "lulc-resnet50-test", "format": "pytorch_state_dict", "architecture": "resnet50",
        "weights_file": weights.name, "weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
        "num_classes": 8, "class_names": EXPECTED_CLASS_NAMES,
        "preprocessing": {"image_size": 256, "color_mode": "RGB", "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]},
    }
    (weights.parent / "model.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    audit = validate_native_package(package)
    assert audit["status"] == "valid", audit
    assert audit["class_map"] == {0: 6, 1: 3, 2: 4, 3: 5, 4: 2, 5: 2, 6: 2, 7: 1}
    envelope = {"protocol_version": "1.0", "request_id": "native-package-smoke", "operation": "pytorch.validate_model",
                "parameters": {"model_package": str(package)}}
    backend = subprocess.run([sys.executable, str(ROOT / "scripts" / "pytorch_backend.py")], input=json.dumps(envelope),
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    backend_result = json.loads(backend.stdout)
    assert backend.returncode == 0 and backend_result["status"] == "completed", backend.stdout

    image = root / "image_2025.tif"
    image.write_bytes(b"spatial fixture is not opened during workflow compilation")
    project = root / "project.json"
    payload = {
        "schema_version": 2, "project_id": "native-resnet50-smoke", "task_type": "classification_only",
        "workspace": "runtime", "security": {"input_roots": [str(root)], "output_root": str(root)},
        "inputs": {"imagery_periods": [{"year": 2025, "path": str(image)}], "imagery": [], "model_package": str(package),
                   "training_roi": None, "historical_lulc": [], "driver_factors": {}},
        "classification": {"enabled": True, "engine": "pytorch", "scheme": "standard_6class",
                           "output_lulc": "outputs/lulc.tif", "output_confidence": "outputs/confidence.tif",
                           "output_low_confidence": None, "low_confidence_threshold": None,
                           "patch_classifier": {"enabled": True, "patch_size": 256, "stride": 256,
                                                "band_indexes": [1, 2, 3], "input_scale": 1.0,
                                                "batch_size": 4, "allow_as_lulc": False},
                           "accuracy": {"enabled": False}},
        "plus": {"enabled": False}, "invest": {"enabled": False}, "subsidence_water": {"enabled": False},
        "ecosystem_service": {"enabled": False}, "gis_outputs": {"enabled": False}, "validation": {"enabled": False},
    }
    project.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    validation = validate(project)
    assert validation["status"] == "valid", validation
    report = compile_workflow(project, root / "runtime" / "generated" / "workflow_job.json")
    job = json.loads(Path(report["workflow_job"]).read_text(encoding="utf-8"))
    stage = next(item for item in job["stages"] if item["id"] == "classification_pytorch")
    command = stage["command"]
    assert command[1].endswith("pytorch_patch_lulc.py"), command
    assert {"--patch-size", "--stride", "--band-indexes", "--input-scale"}.issubset(command), command

    built_project = root / "built" / "project.json"
    built = build(built_project, "native-builder", "runtime", task_type="classification_only",
                  imagery_periods=[{"year": 2025, "path": str(image)}], model_package=str(package),
                  patch_size=256, patch_stride=256, patch_band_indexes=[1, 2, 3], patch_input_scale=1.0)
    built_payload = json.loads(built_project.read_text(encoding="utf-8"))
    assert built["model_mode"] == "registered_resnet50_patch_classifier", built
    assert built_payload["classification"]["scheme"] == "standard_6class", built_payload["classification"]
    assert validate(built_project)["status"] == "valid", validate(built_project)

print(json.dumps({"status": "completed", "checks": ["native manifest", "standard-6 mapping", "project compilation"]}))
