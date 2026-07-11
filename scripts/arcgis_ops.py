#!/usr/bin/env python3
"""Execute declarative ArcGIS Pro raster operations with ArcPy."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


SUPPORTED = {
    "describe", "project_raster", "resample", "extract_by_mask", "slope_aspect",
    "distance_accumulation", "build_raster_attribute_table", "class_area", "combine_transition",
    "w_points_to_raster", "subsidence_water_volume", "export_layout"
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def validate(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    operations = spec.get("operations")
    if not isinstance(operations, list) or not operations:
        return ["operations must be a non-empty list"]
    seen = set()
    for index, operation in enumerate(operations):
        op_id = operation.get("id")
        op_type = operation.get("type")
        if not op_id or op_id in seen:
            errors.append(f"operation {index}: id is missing or duplicated")
        seen.add(op_id)
        if op_type not in SUPPORTED:
            errors.append(f"operation {op_id}: unsupported type {op_type}")
        input_optional = {"combine_transition", "w_points_to_raster", "subsidence_water_volume", "export_layout"}
        if op_type not in input_optional and not operation.get("input"):
            errors.append(f"operation {op_id}: input is required")
        if op_type == "combine_transition" and not operation.get("inputs"):
            errors.append(f"operation {op_id}: inputs are required")
        if op_type == "w_points_to_raster":
            for field in ("table", "x_field", "y_field", "value_field", "output", "cell_size", "coordinate_system"):
                if operation.get(field) in (None, ""):
                    errors.append(f"operation {op_id}: {field} is required")
        if op_type == "subsidence_water_volume":
            for field in ("dem", "subsidence_depth", "water_level_elevation_m", "water_depth_output", "volume_table"):
                if operation.get(field) in (None, ""):
                    errors.append(f"operation {op_id}: {field} is required")
        if op_type == "export_layout":
            for field in ("aprx", "layout_name"):
                if operation.get(field) in (None, ""):
                    errors.append(f"operation {op_id}: {field} is required")
    return errors


def resolve(value: str, workspace: Path) -> str:
    path = Path(value)
    return str(path.resolve() if path.is_absolute() else (workspace / path).resolve())


def ensure_parent(value: str) -> None:
    Path(value).parent.mkdir(parents=True, exist_ok=True)


def describe(arcpy: Any, operation: dict[str, Any], workspace: Path) -> None:
    source = resolve(operation["input"], workspace)
    output = resolve(operation["output"], workspace)
    item = arcpy.Describe(source)
    spatial_reference = getattr(item, "spatialReference", None)
    payload = {
        "path": operation["input"],
        "data_type": getattr(item, "dataType", None),
        "spatial_reference": getattr(spatial_reference, "name", None),
        "factory_code": getattr(spatial_reference, "factoryCode", None),
        "width": getattr(item, "width", None), "height": getattr(item, "height", None),
        "mean_cell_width": getattr(item, "meanCellWidth", None),
        "mean_cell_height": getattr(item, "meanCellHeight", None),
        "pixel_type": getattr(item, "pixelType", None),
        "no_data_value": getattr(item, "noDataValue", None),
        "extent": str(getattr(item, "extent", "")),
    }
    ensure_parent(output)
    Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute_operation(arcpy: Any, operation: dict[str, Any], workspace: Path) -> None:
    op_type = operation["type"]
    if op_type == "describe":
        describe(arcpy, operation, workspace)
        return
    source = resolve(operation["input"], workspace) if operation.get("input") else None
    if op_type == "project_raster":
        output = resolve(operation["output"], workspace); ensure_parent(output)
        arcpy.management.ProjectRaster(source, output, operation["coordinate_system"],
                                       operation.get("resampling", "NEAREST"), operation.get("cell_size"))
    elif op_type == "resample":
        output = resolve(operation["output"], workspace); ensure_parent(output)
        arcpy.management.Resample(source, output, operation["cell_size"], operation.get("resampling", "NEAREST"))
    elif op_type == "extract_by_mask":
        output = resolve(operation["output"], workspace); ensure_parent(output)
        arcpy.sa.ExtractByMask(source, resolve(operation["mask"], workspace)).save(output)
    elif op_type == "slope_aspect":
        slope_output = resolve(operation["slope_output"], workspace); ensure_parent(slope_output)
        aspect_output = resolve(operation["aspect_output"], workspace); ensure_parent(aspect_output)
        arcpy.sa.Slope(source, operation.get("output_measurement", "DEGREE"),
                       operation.get("z_factor", 1), "PLANAR", operation.get("z_unit", "METER")).save(slope_output)
        arcpy.sa.Aspect(source, "PLANAR", operation.get("z_unit", "METER")).save(aspect_output)
    elif op_type == "distance_accumulation":
        output = resolve(operation["output"], workspace); ensure_parent(output)
        arcpy.sa.DistanceAccumulation(source).save(output)
    elif op_type == "build_raster_attribute_table":
        arcpy.management.BuildRasterAttributeTable(source, operation.get("overwrite", "Overwrite"))
    elif op_type == "class_area":
        output = resolve(operation["output"], workspace); ensure_parent(output)
        arcpy.management.BuildRasterAttributeTable(source, "Overwrite")
        desc = arcpy.Describe(source)
        area_ha = abs(float(desc.meanCellWidth) * float(desc.meanCellHeight)) / 10000.0
        with open(output, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream); writer.writerow(["value", "count", "area_ha"])
            with arcpy.da.SearchCursor(source, ["VALUE", "COUNT"]) as rows:
                for value, count in rows:
                    writer.writerow([value, count, count * area_ha])
    elif op_type == "combine_transition":
        inputs = [resolve(item, workspace) for item in operation["inputs"]]
        combined = resolve(operation["combined_output"], workspace); ensure_parent(combined)
        table = resolve(operation["output"], workspace); ensure_parent(table)
        arcpy.sa.Combine(inputs).save(combined)
        fields = [field.name for field in arcpy.ListFields(combined)
                  if field.type not in ("OID", "Geometry") and field.name.upper() not in ("VALUE", "COUNT")]
        if len(fields) < 2:
            raise RuntimeError("Combine output does not contain two source-class fields")
        desc = arcpy.Describe(combined)
        area_ha = abs(float(desc.meanCellWidth) * float(desc.meanCellHeight)) / 10000.0
        with open(table, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream); writer.writerow(["from_class", "to_class", "count", "area_ha"])
            with arcpy.da.SearchCursor(combined, [fields[0], fields[1], "COUNT"]) as rows:
                for old, new, count in rows:
                    writer.writerow([old, new, count, count * area_ha])
    elif op_type == "w_points_to_raster":
        table = resolve(operation["table"], workspace)
        points = resolve(operation.get("points_output", f"intermediate/{operation['id']}_points.shp"), workspace)
        output = resolve(operation["output"], workspace)
        ensure_parent(points); ensure_parent(output)
        arcpy.management.XYTableToPoint(table, points, operation["x_field"], operation["y_field"], None,
                                        operation["coordinate_system"])
        arcpy.conversion.PointToRaster(points, operation["value_field"], output, "MEAN", "NONE", operation["cell_size"])
    elif op_type == "subsidence_water_volume":
        dem = arcpy.sa.Raster(resolve(operation["dem"], workspace))
        subsidence = arcpy.sa.Raster(resolve(operation["subsidence_depth"], workspace))
        water_level = float(operation["water_level_elevation_m"])
        post_mining = dem - subsidence
        depth = arcpy.sa.SetNull(post_mining >= water_level, water_level - post_mining)
        if operation.get("mask"):
            depth = arcpy.sa.ExtractByMask(depth, resolve(operation["mask"], workspace))
        depth_output = resolve(operation["water_depth_output"], workspace); ensure_parent(depth_output)
        depth.save(depth_output)
        zone = arcpy.sa.SetNull(arcpy.sa.IsNull(depth), 1, "VALUE = 1")
        zone_output = resolve(operation.get("zone_output", f"intermediate/{operation['id']}_zone.tif"), workspace)
        ensure_parent(zone_output); zone.save(zone_output)
        table = resolve(operation.get("zonal_table", f"intermediate/{operation['id']}_zonal.dbf"), workspace)
        ensure_parent(table)
        arcpy.sa.ZonalStatisticsAsTable(zone_output, "VALUE", depth_output, table, "DATA", "SUM")
        sum_depth = 0.0
        with arcpy.da.SearchCursor(table, ["SUM"]) as rows:
            for (value,) in rows:
                sum_depth += float(value or 0)
        desc = arcpy.Describe(depth_output)
        pixel_area_m2 = abs(float(desc.meanCellWidth) * float(desc.meanCellHeight))
        volume_table = resolve(operation["volume_table"], workspace); ensure_parent(volume_table)
        with open(volume_table, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["water_level_elevation_m", "sum_water_depth_m", "pixel_area_m2", "water_volume_m3"])
            writer.writerow([water_level, sum_depth, pixel_area_m2, sum_depth * pixel_area_m2])
    elif op_type == "export_layout":
        aprx = arcpy.mp.ArcGISProject(resolve(operation["aprx"], workspace))
        layouts = [item for item in aprx.listLayouts() if item.name == operation["layout_name"]]
        if not layouts:
            raise RuntimeError(f"layout not found: {operation['layout_name']}")
        layout = layouts[0]
        resolution = int(operation.get("resolution", 300))
        if operation.get("pdf"):
            pdf = resolve(operation["pdf"], workspace); ensure_parent(pdf)
            layout.exportToPDF(pdf, resolution=resolution)
        if operation.get("png"):
            png = resolve(operation["png"], workspace); ensure_parent(png)
            layout.exportToPNG(png, resolution=resolution)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--validate-spec", action="store_true")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    spec = load_json(args.spec.resolve())
    errors = validate(spec)
    if errors:
        raise SystemExit("\n".join(errors))
    if args.validate_spec:
        print("VALID")
        return 0
    import arcpy
    if args.probe:
        print(json.dumps({"version": arcpy.GetInstallInfo().get("Version"),
                          "product": arcpy.ProductInfo()}, ensure_ascii=False))
        return 0
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    environment = dict(spec.get("environment", {}))
    for key in ("snapRaster", "cellSize", "extent", "mask"):
        if isinstance(environment.get(key), str):
            environment[key] = resolve(environment[key], workspace)
    with arcpy.EnvManager(**environment):
        for operation in spec["operations"]:
            execute_operation(arcpy, operation, workspace)
            print(f"COMPLETED {operation['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
