#!/usr/bin/env python3
"""Execute declarative ArcGIS Pro raster operations with ArcPy."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from subsidence_water_carbon import calculate_components, calculate_invest_replacement


SUPPORTED = {
    "describe", "project_raster", "resample", "extract_by_mask", "slope_aspect",
    "distance_accumulation", "build_raster_attribute_table", "class_area", "combine_transition",
    "w_points_to_raster", "subsidence_water_volume", "subsidence_water_carbon", "export_layout"
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
        input_optional = {
            "combine_transition", "w_points_to_raster", "subsidence_water_volume", "subsidence_water_carbon",
            "export_layout"
        }
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
        if op_type == "subsidence_water_carbon":
            required = (
                "dem", "subsidence_depth", "water_boundary", "water_level_elevation_m", "water_depth_output",
                "aquatic_vegetation_output", "bottom_sediment_output", "volume_table", "carbon_table",
                "water_carbon_density_g_c_m3", "aquatic_vegetation_carbon_density_t_c_ha",
                "bottom_sediment_carbon_density_t_c_ha",
            )
            for field in required:
                if operation.get(field) in (None, ""):
                    errors.append(f"operation {op_id}: {field} is required")
            for field in (
                "water_level_elevation_m", "water_carbon_density_g_c_m3",
                "aquatic_vegetation_carbon_density_t_c_ha", "bottom_sediment_carbon_density_t_c_ha",
            ):
                value = operation.get(field)
                if value not in (None, "") and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"operation {op_id}: {field} must be a non-negative number")
            vegetation_mask = operation.get("aquatic_vegetation_mask")
            threshold = operation.get("aquatic_vegetation_depth_threshold_m")
            if not vegetation_mask and (not isinstance(threshold, (int, float)) or threshold < 0):
                errors.append(
                    f"operation {op_id}: provide aquatic_vegetation_mask or a non-negative "
                    "aquatic_vegetation_depth_threshold_m"
                )
            if not operation.get("bottom_sediment_mask") and operation.get("bottom_sediment_assume_full_waterbed") is not True:
                errors.append(
                    f"operation {op_id}: provide bottom_sediment_mask or set "
                    "bottom_sediment_assume_full_waterbed to true explicitly"
                )
            invest_total = operation.get("invest_total_carbon_t_c")
            invest_water = operation.get("invest_subsidence_water_carbon_t_c")
            if (invest_total is None) != (invest_water is None):
                errors.append(
                    f"operation {op_id}: invest_total_carbon_t_c and "
                    "invest_subsidence_water_carbon_t_c must be supplied together"
                )
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


def subsidence_water_depth(arcpy: Any, operation: dict[str, Any], workspace: Path) -> tuple[Any, float]:
    """Construct positive water depth from a pre-mining DEM, PIM depth, level, and observed water boundary."""
    dem = arcpy.sa.Raster(resolve(operation["dem"], workspace))
    subsidence = arcpy.sa.Raster(resolve(operation["subsidence_depth"], workspace))
    water_level = float(operation["water_level_elevation_m"])
    post_mining = dem - subsidence
    depth = arcpy.sa.SetNull(post_mining >= water_level, water_level - post_mining)
    boundary = operation.get("water_boundary") or operation.get("mask")
    if boundary:
        depth = arcpy.sa.ExtractByMask(depth, resolve(boundary, workspace))
    return depth, water_level


def raster_metrics(arcpy: Any, raster: str, workspace: Path, metric_id: str) -> dict[str, float]:
    """Return count, depth sum, area, and volume using tools available in ArcGIS Pro 3.0."""
    desc = arcpy.Describe(raster)
    pixel_area_m2 = abs(float(desc.meanCellWidth) * float(desc.meanCellHeight))
    if str(arcpy.management.GetRasterProperties(raster, "ALLNODATA").getOutput(0)) == "1":
        return {
            "pixel_area_m2": pixel_area_m2,
            "cell_count": 0.0,
            "sum_depth_m": 0.0,
            "area_ha": 0.0,
            "volume_m3": 0.0,
        }
    zone = arcpy.sa.SetNull(arcpy.sa.IsNull(raster), 1, "VALUE = 1")
    zone_output = resolve(f"intermediate/{metric_id}_zone.tif", workspace)
    ensure_parent(zone_output)
    zone.save(zone_output)
    table = resolve(f"intermediate/{metric_id}_zonal.dbf", workspace)
    ensure_parent(table)
    arcpy.sa.ZonalStatisticsAsTable(zone_output, "VALUE", raster, table, "DATA", "ALL")
    count = 0.0
    total = 0.0
    with arcpy.da.SearchCursor(table, ["COUNT", "SUM"]) as rows:
        for cell_count, value_sum in rows:
            count += float(cell_count or 0)
            total += float(value_sum or 0)
    return {
        "pixel_area_m2": pixel_area_m2,
        "cell_count": count,
        "sum_depth_m": total,
        "area_ha": count * pixel_area_m2 / 10000.0,
        "volume_m3": total * pixel_area_m2,
    }


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
    elif op_type == "subsidence_water_carbon":
        # Implements the thesis section 4.3 chain: observed water boundary + subsidence terrain -> volume -> 3 components.
        depth, water_level = subsidence_water_depth(arcpy, operation, workspace)
        depth_output = resolve(operation["water_depth_output"], workspace); ensure_parent(depth_output)
        depth.save(depth_output)
        volume = raster_metrics(arcpy, depth_output, workspace, f"{operation['id']}_water_depth")
        if volume["cell_count"] <= 0 or volume["volume_m3"] <= 0:
            raise RuntimeError("water boundary and terrain produced no positive water-depth cells")

        if operation.get("aquatic_vegetation_mask"):
            vegetation = arcpy.sa.ExtractByMask(
                arcpy.sa.Raster(depth_output), resolve(operation["aquatic_vegetation_mask"], workspace)
            )
            vegetation_basis = "observed_or_interpreted_aquatic_vegetation_mask"
        else:
            threshold = float(operation["aquatic_vegetation_depth_threshold_m"])
            vegetation = arcpy.sa.SetNull(arcpy.sa.Raster(depth_output) > threshold, arcpy.sa.Raster(depth_output))
            vegetation_basis = f"water_depth_less_than_or_equal_to_{threshold}_m"
        vegetation_output = resolve(operation["aquatic_vegetation_output"], workspace); ensure_parent(vegetation_output)
        vegetation.save(vegetation_output)
        vegetation_area = raster_metrics(
            arcpy, vegetation_output, workspace, f"{operation['id']}_aquatic_vegetation"
        )["area_ha"]

        if operation.get("bottom_sediment_mask"):
            sediment = arcpy.sa.ExtractByMask(arcpy.sa.Raster(depth_output), resolve(operation["bottom_sediment_mask"], workspace))
            sediment_basis = "observed_or_interpreted_bottom_sediment_mask"
        else:
            sediment = arcpy.sa.Raster(depth_output)
            sediment_basis = "full_waterbed_explicit_assumption"
        sediment_output = resolve(operation["bottom_sediment_output"], workspace); ensure_parent(sediment_output)
        sediment.save(sediment_output)
        sediment_area = raster_metrics(
            arcpy, sediment_output, workspace, f"{operation['id']}_bottom_sediment"
        )["area_ha"]

        components = calculate_components(
            water_volume_m3=volume["volume_m3"],
            water_carbon_density_g_c_m3=float(operation["water_carbon_density_g_c_m3"]),
            aquatic_vegetation_area_ha=vegetation_area,
            aquatic_vegetation_carbon_density_t_c_ha=float(operation["aquatic_vegetation_carbon_density_t_c_ha"]),
            bottom_sediment_area_ha=sediment_area,
            bottom_sediment_carbon_density_t_c_ha=float(operation["bottom_sediment_carbon_density_t_c_ha"]),
        )
        enhanced_total: float | str = ""
        if operation.get("invest_total_carbon_t_c") is not None:
            enhanced_total = calculate_invest_replacement(
                invest_total_carbon_t_c=float(operation["invest_total_carbon_t_c"]),
                invest_subsidence_water_carbon_t_c=float(operation["invest_subsidence_water_carbon_t_c"]),
                composite_carbon_t_c=components["subsidence_water_composite_carbon_t_c"],
            )

        volume_table = resolve(operation["volume_table"], workspace); ensure_parent(volume_table)
        with open(volume_table, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "water_level_elevation_m", "pixel_area_m2", "water_cell_count", "water_area_ha",
                "sum_water_depth_m", "water_volume_m3", "water_boundary"
            ])
            writer.writeheader()
            writer.writerow({
                "water_level_elevation_m": water_level,
                "pixel_area_m2": volume["pixel_area_m2"],
                "water_cell_count": volume["cell_count"],
                "water_area_ha": volume["area_ha"],
                "sum_water_depth_m": volume["sum_depth_m"],
                "water_volume_m3": volume["volume_m3"],
                "water_boundary": operation["water_boundary"],
            })
        carbon_table = resolve(operation["carbon_table"], workspace); ensure_parent(carbon_table)
        with open(carbon_table, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "water_volume_m3", "water_carbon_density_g_c_m3", "water_carbon_t_c",
                "aquatic_vegetation_basis", "aquatic_vegetation_area_ha",
                "aquatic_vegetation_carbon_density_t_c_ha", "aquatic_vegetation_carbon_t_c",
                "bottom_sediment_basis", "bottom_sediment_area_ha", "bottom_sediment_carbon_density_t_c_ha",
                "bottom_sediment_carbon_t_c", "subsidence_water_composite_carbon_t_c",
                "invest_total_carbon_t_c", "invest_subsidence_water_carbon_t_c", "enhanced_invest_total_carbon_t_c",
            ])
            writer.writeheader()
            writer.writerow({
                "water_volume_m3": volume["volume_m3"],
                "water_carbon_density_g_c_m3": operation["water_carbon_density_g_c_m3"],
                "water_carbon_t_c": components["water_carbon_t_c"],
                "aquatic_vegetation_basis": vegetation_basis,
                "aquatic_vegetation_area_ha": vegetation_area,
                "aquatic_vegetation_carbon_density_t_c_ha": operation["aquatic_vegetation_carbon_density_t_c_ha"],
                "aquatic_vegetation_carbon_t_c": components["aquatic_vegetation_carbon_t_c"],
                "bottom_sediment_basis": sediment_basis,
                "bottom_sediment_area_ha": sediment_area,
                "bottom_sediment_carbon_density_t_c_ha": operation["bottom_sediment_carbon_density_t_c_ha"],
                "bottom_sediment_carbon_t_c": components["bottom_sediment_carbon_t_c"],
                "subsidence_water_composite_carbon_t_c": components["subsidence_water_composite_carbon_t_c"],
                "invest_total_carbon_t_c": operation.get("invest_total_carbon_t_c", ""),
                "invest_subsidence_water_carbon_t_c": operation.get("invest_subsidence_water_carbon_t_c", ""),
                "enhanced_invest_total_carbon_t_c": enhanced_total,
            })
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
