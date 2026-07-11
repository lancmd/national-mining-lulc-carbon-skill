"""Create tiny projected rasters used only by the ArcPy smoke test."""

from pathlib import Path
import arcpy


workspace = Path(__file__).resolve().parents[1] / "outputs" / "arcgis_smoke"
workspace.mkdir(parents=True, exist_ok=True)
arcpy.env.overwriteOutput = True
spatial_reference = arcpy.SpatialReference(32650)
origin = arcpy.Point(500000, 3700000)
dem = arcpy.sa.CreateConstantRaster(100, "FLOAT", 30, arcpy.Extent(500000, 3700000, 500300, 3700300))
dem.save(str(workspace / "dem.tif"))
arcpy.management.DefineProjection(str(workspace / "dem.tif"), spatial_reference)
lulc = arcpy.sa.CreateConstantRaster(4, "INTEGER", 30, arcpy.Extent(500000, 3700000, 500300, 3700300))
lulc.save(str(workspace / "lulc.tif"))
arcpy.management.DefineProjection(str(workspace / "lulc.tif"), spatial_reference)
subsidence = arcpy.sa.CreateConstantRaster(2, "FLOAT", 30, arcpy.Extent(500000, 3700000, 500300, 3700300))
subsidence.save(str(workspace / "subsidence_depth.tif"))
arcpy.management.DefineProjection(str(workspace / "subsidence_depth.tif"), spatial_reference)
print(workspace)
