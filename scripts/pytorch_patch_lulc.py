#!/usr/bin/env python3
"""Run the registered ResNet-50 image classifier as an explicit patch-grid LULC model.

The model package produced for the iFLYTEK challenge is a whole-image classifier:
it returns one label for one RGB patch.  It is not a semantic-segmentation model.
This adapter therefore writes a labelled *patch grid* and records that limitation
in its sidecar report.  It never presents the result as pixel-wise segmentation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


NATIVE_MANIFEST = Path("model") / "model.json"
EXPECTED_CLASS_NAMES = [
    "其他用地", "耕地", "林地", "草地与其他绿地", "城乡住宅与商业用地",
    "工业用地", "交通运输用地", "水域与水利设施用地",
]
# The native classifier does not distinguish natural water from subsidence water.
# This aggregation is only valid for the ordinary six-class MAESA scheme.
STANDARD6_BY_NATIVE_INDEX = {0: 6, 1: 3, 2: 4, 3: 5, 4: 2, 5: 2, 6: 2, 7: 1}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_native_resnet50_package(package: Path) -> bool:
    return (package / NATIVE_MANIFEST).is_file()


def load_native_manifest(package: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = package / NATIVE_MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing native model manifest: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8-sig") as stream:
        manifest = json.load(stream)
    if not isinstance(manifest, dict):
        raise ValueError("native model manifest must be a JSON object")
    weights_name = manifest.get("weights_file")
    if not isinstance(weights_name, str) or not weights_name:
        raise ValueError("native model manifest has no weights_file")
    relative = Path(weights_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("weights_file must be a package-relative path")
    return manifest, package / "model" / relative


def native_class_map(manifest: dict[str, Any]) -> dict[int, int] | None:
    names = manifest.get("class_names")
    if names == EXPECTED_CLASS_NAMES:
        return STANDARD6_BY_NATIVE_INDEX.copy()
    return None


def validate_native_package(package: Path, verify_weights: bool = True) -> dict[str, Any]:
    """Validate the user-supplied ResNet-50 package without importing PyTorch."""
    errors: list[str] = []
    warnings: list[str] = [
        "this package is an RGB patch classifier, not a semantic-segmentation model",
        "training sensor, spatial resolution, patch footprint, and independent validation metrics are not declared",
        "cross-region or cross-sensor use remains pending_validation",
    ]
    try:
        manifest, weights = load_native_manifest(package)
    except Exception as error:
        return {"status": "invalid", "errors": [str(error)], "warnings": warnings}
    if manifest.get("format") != "pytorch_state_dict":
        errors.append("native model format must be pytorch_state_dict")
    if manifest.get("architecture") != "resnet50":
        errors.append("native model architecture must be resnet50")
    class_count = manifest.get("num_classes")
    names = manifest.get("class_names")
    if not isinstance(class_count, int) or class_count < 2:
        errors.append("num_classes must be an integer >= 2")
    if not isinstance(names, list) or len(names) != class_count or any(not isinstance(name, str) or not name for name in names):
        errors.append("class_names must be a non-empty string list matching num_classes")
    preprocessing = manifest.get("preprocessing")
    if not isinstance(preprocessing, dict):
        errors.append("preprocessing must be an object")
        preprocessing = {}
    else:
        if preprocessing.get("color_mode") != "RGB":
            errors.append("native ResNet-50 adapter requires RGB preprocessing")
        image_size = preprocessing.get("image_size")
        if not isinstance(image_size, int) or image_size < 16:
            errors.append("preprocessing.image_size must be an integer >= 16")
        for field in ("mean", "std"):
            values = preprocessing.get(field)
            if not isinstance(values, list) or len(values) != 3 or not all(isinstance(value, (int, float)) for value in values):
                errors.append(f"preprocessing.{field} must contain three numeric values")
        if isinstance(preprocessing.get("std"), list) and any(float(value) <= 0 for value in preprocessing["std"]):
            errors.append("preprocessing.std values must be positive")
    actual_hash = None
    if not weights.is_file():
        errors.append(f"weights file does not exist: {weights}")
    elif verify_weights:
        actual_hash = file_sha256(weights)
        expected_hash = str(manifest.get("weights_sha256", "")).lower()
        if not expected_hash:
            errors.append("weights_sha256 is required")
        elif actual_hash != expected_hash:
            errors.append("weights_sha256 does not match the native model manifest")
    mapping = native_class_map(manifest)
    if mapping is None:
        errors.append("the native classes have no reviewed mapping to the standard_6class scheme")
    return {
        "status": "valid" if not errors else "invalid",
        "model_id": manifest.get("name"),
        "format": manifest.get("format"),
        "architecture": manifest.get("architecture"),
        "weights": str(weights),
        "actual_sha256": actual_hash,
        "class_count": class_count,
        "class_names": names,
        "output_scheme": "standard_6class" if mapping else None,
        "class_map": mapping,
        "inference_mode": "patch_classifier",
        "errors": errors,
        "warnings": warnings,
    }


def _positions(length: int, stride: int) -> list[int]:
    return list(range(0, length, stride))


def _parse_band_indexes(value: str) -> list[int]:
    try:
        indexes = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise ValueError("band_indexes must be comma-separated positive integers") from error
    if len(indexes) != 3 or any(item < 1 for item in indexes) or len(set(indexes)) != 3:
        raise ValueError("band_indexes must contain three distinct positive RGB band indexes")
    return indexes


def _load_resnet50(manifest: dict[str, Any], weights: Path, device: str):
    try:
        import torch
        import torch.nn as nn
        from torchvision import models
    except ImportError as error:
        raise RuntimeError("native ResNet-50 inference requires torch and torchvision; run setup_agent.ps1 -WithPyTorch") from error
    try:
        checkpoint = torch.load(str(weights), map_location="cpu", weights_only=True)
    except TypeError as error:
        raise RuntimeError("the installed PyTorch does not support safe weights_only loading; install torch >= 2.4") from error
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        state_dict = checkpoint["model_state_dict"]
    elif isinstance(checkpoint, dict) and "state_dict" in checkpoint:
        state_dict = checkpoint["state_dict"]
    else:
        state_dict = checkpoint
    if not isinstance(state_dict, dict):
        raise ValueError("weights file does not contain a state_dict")
    state_dict = {key[7:] if str(key).startswith("module.") else key: value for key, value in state_dict.items()}
    model = models.resnet50(weights=None)
    model.fc = nn.Linear(model.fc.in_features, int(manifest["num_classes"]))
    model.load_state_dict(state_dict, strict=True)
    model.to(device).eval()
    return model


def infer_patch_grid(package: Path, input_raster: Path, class_output: Path, confidence_output: Path, *,
                     patch_size: int, stride: int, band_indexes: list[int], input_scale: float,
                     device_name: str = "auto", low_confidence_output: Path | None = None,
                     low_confidence_threshold: float | None = None, batch_size: int | None = None) -> dict[str, Any]:
    """Create a coarse, explicitly labelled patch grid from the native ResNet-50 model."""
    validation = validate_native_package(package)
    if validation["status"] != "valid":
        raise ValueError("invalid native model package: " + "; ".join(validation["errors"]))
    if not isinstance(patch_size, int) or patch_size < 16:
        raise ValueError("patch_size must be an integer >= 16")
    if not isinstance(stride, int) or not 1 <= stride <= patch_size:
        raise ValueError("stride must be an integer from 1 through patch_size")
    if not isinstance(input_scale, (int, float)) or not math.isfinite(float(input_scale)) or float(input_scale) <= 0:
        raise ValueError("input_scale must be a finite positive number")
    if low_confidence_threshold is not None and (not 0 < float(low_confidence_threshold) < 1):
        raise ValueError("low_confidence_threshold must be between 0 and 1")
    try:
        import numpy as np
        import rasterio
        from affine import Affine
        from rasterio.windows import Window
        import torch
    except ImportError as error:
        raise RuntimeError("native ResNet-50 inference requires numpy, rasterio, torch, torchvision, and affine") from error
    manifest, weights = load_native_manifest(package)
    if device_name == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = device_name
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable")
    model = _load_resnet50(manifest, weights, device)
    preprocessing = manifest["preprocessing"]
    mean = np.asarray(preprocessing["mean"], dtype="float32")[:, None, None]
    std = np.asarray(preprocessing["std"], dtype="float32")[:, None, None]
    mapping = validation["class_map"]
    native_count = int(manifest["num_classes"])
    batch_size = int(batch_size or (32 if device.startswith("cuda") else 4))
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    class_output.parent.mkdir(parents=True, exist_ok=True)
    confidence_output.parent.mkdir(parents=True, exist_ok=True)
    if low_confidence_output:
        low_confidence_output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(input_raster) as source:
        if not source.crs:
            raise ValueError("input raster CRS is missing")
        if max(band_indexes) > source.count:
            raise ValueError(f"input raster has {source.count} bands but RGB indexes require {max(band_indexes)}")
        rows, cols = _positions(source.height, stride), _positions(source.width, stride)
        transform = source.transform * Affine.scale(stride, stride)
        class_profile = {"driver": "GTiff", "width": len(cols), "height": len(rows), "count": 1, "dtype": "uint8",
                         "crs": source.crs, "transform": transform, "nodata": 0, "compress": "deflate"}
        confidence_profile = {**class_profile, "dtype": "float32", "nodata": -9999.0}
        low_profile = {**class_profile, "dtype": "uint8", "nodata": 255}
        with rasterio.open(class_output, "w", **class_profile) as class_sink, \
                rasterio.open(confidence_output, "w", **confidence_profile) as confidence_sink:
            low_sink = rasterio.open(low_confidence_output, "w", **low_profile) if low_confidence_output else None
            try:
                for output_row, row in enumerate(rows):
                    labels = np.zeros(len(cols), dtype="uint8")
                    confidence = np.full(len(cols), -9999.0, dtype="float32")
                    low = np.full(len(cols), 255, dtype="uint8")
                    pending: list[tuple[int, Any]] = []
                    for output_col, col in enumerate(cols):
                        offset = (patch_size - stride) / 2
                        window = Window(col - offset, row - offset, patch_size, patch_size)
                        image = source.read(band_indexes, window=window, boundless=True, masked=True).astype("float32")
                        valid = ~np.any(np.ma.getmaskarray(image), axis=0)
                        if float(valid.mean()) < 0.5:
                            continue
                        data = image.filled(0.0)
                        pending.append((output_col, ((data * float(input_scale)) - mean) / std))
                        if len(pending) == batch_size:
                            _predict_batch(model, pending, labels, confidence, low, mapping, device, native_count, low_confidence_threshold, torch, np)
                            pending = []
                    if pending:
                        _predict_batch(model, pending, labels, confidence, low, mapping, device, native_count, low_confidence_threshold, torch, np)
                    class_sink.write(labels[None, None, :], window=Window(0, output_row, len(cols), 1))
                    confidence_sink.write(confidence[None, None, :], window=Window(0, output_row, len(cols), 1))
                    if low_sink:
                        low_sink.write(low[None, None, :], window=Window(0, output_row, len(cols), 1))
            finally:
                if low_sink:
                    low_sink.close()
        resolution_x, resolution_y = abs(float(source.transform.a)), abs(float(source.transform.e))
    report = {
        "status": "completed", "model_id": manifest["name"], "model_sha256": validation["actual_sha256"],
        "inference_mode": "patch_classifier", "output_kind": "coarse_patch_grid_not_pixelwise_segmentation",
        "validation_status": "pending_validation", "input_raster": str(input_raster.resolve()),
        "class_output": str(class_output.resolve()), "confidence_output": str(confidence_output.resolve()),
        "low_confidence_output": str(low_confidence_output.resolve()) if low_confidence_output else None,
        "device": device, "band_indexes": band_indexes, "input_scale": float(input_scale),
        "patch_size_pixels": patch_size, "stride_pixels": stride,
        "patch_size_m": [patch_size * resolution_x, patch_size * resolution_y],
        "output_cell_size_m": [stride * resolution_x, stride * resolution_y],
        "class_map_to_standard_6class": mapping,
        "warnings": validation["warnings"],
    }
    class_output.with_suffix(class_output.suffix + ".inference.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _predict_batch(model: Any, pending: list[tuple[int, Any]], labels: Any, confidence: Any, low: Any,
                   mapping: dict[int, int], device: str, native_count: int, threshold: float | None,
                   torch: Any, np: Any) -> None:
    tensor = torch.from_numpy(np.stack([item[1] for item in pending])).to(device)
    with torch.inference_mode():
        logits = model(tensor)
        if logits.ndim != 2 or logits.shape != (len(pending), native_count):
            raise ValueError(f"ResNet-50 output must be [batch,{native_count}], got {tuple(logits.shape)}")
        probabilities = torch.softmax(logits, dim=1)
        scores, indexes = probabilities.max(dim=1)
    for (output_col, _), score, index in zip(pending, scores.detach().cpu().tolist(), indexes.detach().cpu().tolist()):
        labels[output_col] = int(mapping[int(index)])
        confidence[output_col] = float(score)
        low[output_col] = int(float(score) < float(threshold)) if threshold is not None else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="validate a native ResNet-50 package without loading PyTorch")
    audit.add_argument("--model-package", required=True, type=Path)
    audit.add_argument("--output", type=Path)
    infer = commands.add_parser("infer", help="write an explicit coarse patch-grid classification")
    infer.add_argument("--model-package", required=True, type=Path)
    infer.add_argument("--input-raster", required=True, type=Path)
    infer.add_argument("--class-output", required=True, type=Path)
    infer.add_argument("--confidence-output", required=True, type=Path)
    infer.add_argument("--patch-size", type=int, required=True)
    infer.add_argument("--stride", type=int, required=True)
    infer.add_argument("--band-indexes", required=True, help="three comma-separated 1-based RGB band indexes")
    infer.add_argument("--input-scale", type=float, required=True, help="source value scale before ImageNet normalisation")
    infer.add_argument("--device", default="auto")
    infer.add_argument("--batch-size", type=int)
    infer.add_argument("--low-confidence-output", type=Path)
    infer.add_argument("--low-confidence-threshold", type=float)
    args = parser.parse_args()
    if args.command == "audit":
        result = validate_native_package(args.model_package.resolve())
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "valid" else 1
    result = infer_patch_grid(args.model_package.resolve(), args.input_raster.resolve(), args.class_output.resolve(),
                              args.confidence_output.resolve(), patch_size=args.patch_size, stride=args.stride,
                              band_indexes=_parse_band_indexes(args.band_indexes), input_scale=args.input_scale,
                              device_name=args.device, low_confidence_output=args.low_confidence_output.resolve() if args.low_confidence_output else None,
                              low_confidence_threshold=args.low_confidence_threshold, batch_size=args.batch_size)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
