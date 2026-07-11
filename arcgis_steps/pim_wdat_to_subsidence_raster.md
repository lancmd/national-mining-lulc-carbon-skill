# ArcGIS Pro：由外部 w.dat / w.txt 生成沉陷云图并接入 PLUS

本流程参考《20241015 采煤沉陷 ArcGIS 出图方法》，把沉陷预计软件已经计算完成的 `w.dat`、`w.txt` 或 CSV 转换为沉陷点、分析栅格、沉陷边界、等值线和沉陷云图，并另行生成与 PLUS 主网格对齐的驱动栅格。

本流程只进行 GIS 格式转换、表面重建和制图表达，不计算概率积分法参数，也不根据采矿参数预测新的下沉值。

## 1. 输入审计

输入至少应提供 `X`、`Y`、`W`，或提供原点、行列数、网格间距和排列顺序。记录：

- 坐标系和水平单位；
- W 的含义、单位和正负号约定；
- 预计年份、工作面 ID 和方案 ID；
- 沉陷软件名称、版本和导出日期；
- 规则网格间距及点的排列方式。

源文档通过 Surfer 打开 W 文件，将前五列复制到 Excel，再保存为制表符分隔文本。若原文件已能被 ArcGIS 正确解析，可直接导入；若经 Excel 中转，必须防止坐标被科学计数法截断、空值变为 0，并核对中转前后行数。

只有 W 值、没有可靠空间定义时，应由沉陷软件重新导出。本项目不根据点序号猜测坐标。

## 2. 字段与数值检查

导入前检查：

- X/Y 字段和 W 字段是否为 Double；
- X/Y 是否落在预计工作面附近；
- X/Y 唯一组合是否重复；
- 点数是否等于预期行数乘列数；
- 相邻坐标差是否符合声明的网格间距；
- W 是否存在空值、文本值或异常数量级。

复制原始文件并保持只读，所有字段变换在标准化副本中完成。

## 3. 添加 XY 点

可将文本直接拖入 ArcGIS Pro，再运行 `XY Table To Point`：

- X Field：实际 X 坐标列；
- Y Field：实际 Y 坐标列；
- Coordinate System：外部文件真实 CRS；
- 输出：File Geodatabase 要素类，跨软件交换时可用 GeoPackage。

参考文档使用 `CGCS2000_3_Degree_GK_Zone_39`，该设置只适用于数据确属 CGCS2000 3°带第 39 带的情况，不能作为其他矿区默认值。

导入后叠加矿界和工作面检查位置。位置错误时排查 X/Y 顺序、投影带号、假东移、坐标单位和 CRS，不能用“定义投影”强行移动数据。

## 4. 同时保留有符号 W 和非负深度

建议保留两个 Double 字段：

- `W_M`：保持外部软件正负号的米制 W；
- `DEPTH_M`：统一为非负的下沉深度。

若外部约定“下沉为负”且 W 单位为 mm：

```text
W_M = W / 1000
DEPTH_M = W / -1000
```

参考文档的 `Field5 / -1000` 对应 `DEPTH_M`。不要直接覆盖原始 W，也不要无条件使用绝对值；若外部软件采用“下沉为正”，应按其说明调整。

后续边界与等值线必须统一选择一套字段：使用 `W_M` 时下沉阈值为负，使用 `DEPTH_M` 时阈值为正。不得对正深度栅格继续套用 `-0.01 m`。

## 5. 分析栅格：规则点直接转栅格

若外部 W 点是规则网格，运行 `Point to Raster`：

- Value field：`DEPTH_M`；
- Cell assignment：点唯一时可用 Most frequent；若一个像元包含多点，应选择 Mean 并说明；
- Cell size：使用外部软件的实际网格间距；
- 输出：`subsidence_depth_raw.tif`。

参考文档示例像元大小为 1 m，但只在原始点间距和研究目的支持时使用，不能固定套用。

该栅格用于数值检查和 PLUS 接入。规则点转栅格是格式转换，不是重新预计。

## 6. 制图栅格：TIN 表面重建

为生成连续沉陷云图，可按参考文档建立制图分支：

1. 运行 `Create TIN`；
2. 坐标系使用输入点真实投影；
3. 输入要素使用沉陷点；
4. Height Field 选择 `W_M` 或 `DEPTH_M`；
5. SF Type 选择 `Mass_Points`；
6. 运行 `TIN To Raster`；
7. Method 选择 Linear；
8. Sampling Distance 选择 Cell Size。

参考文档的云图示例采样值为 5 m。该值属于制图分辨率，应结合原始点间距、地图比例尺和计算量选择；不得将 5 m 平滑云图解释为 5 m 精度的沉陷观测。

输出示例：`subsidence_surface_cartographic.tif`。该表面是由外部 W 值重建的制图产品，不是新的 PIM 预测结果。

## 7. 提取沉陷边界

参考文档使用 `Contour List` 提取接近零下沉的边界。推荐把最小有效下沉阈值设置为可解释参数，例如 0.01 m，并与字段符号保持一致：

- 使用有符号 `W_M`：阈值示例为 `-0.01 m`；
- 使用非负 `DEPTH_M`：阈值示例为 `+0.01 m`。

阈值应根据沉陷软件输出精度、背景噪声和制图目的调整，不是全国统一标准。输出线经拓扑检查后，可运行 `Feature To Polygon` 得到沉陷边界面。

## 8. 裁剪沉陷云图

运行 `Clip Raster`，以沉陷边界面裁剪 TIN 转栅格结果，并勾选使用输入要素裁剪几何。输出建议：`subsidence_cloud_clipped.tif`。

分析版本保持边界外为 NoData。参考文档导出时将 NoData 设为 0，适合部分显示需求，但会混淆“无数据”和“零下沉”；如需兼容该显示方式，应另存 `_display.tif`，不得覆盖分析栅格。

## 9. 绘制沉陷等值线

可使用 `Contour` 或参考文档中的 `Contour with Barriers`：

- Input raster：裁剪后的沉陷云图；
- Barrier features：有明确阻隔边界时再提供；
- Contour interval：按数据范围和地图比例尺设置；
- Base contour：通常设为 0；
- Explicit contour：可加入边界阈值；
- Z factor：单位一致时为 1。

参考文档示例间距为 0.5 m、显式等值线为 `-0.01 m`。只有使用负值 `W_M` 栅格时才沿用负阈值；若使用 `DEPTH_M`，应改为正值。等值线只是对已有沉陷表面的制图表达。

## 10. 等值线范围面

将沉陷边界线与内部等值线进行拓扑检查后运行 `Feature To Polygon`，得到不同下沉等级范围面。新增文本或数值字段记录下沉范围，并逐面核对属性与等值线值。

优先输出到 File Geodatabase 或 GeoPackage；只有现有协作流程明确要求时才额外导出 Shapefile。

## 11. PLUS 驱动栅格

PLUS 使用数值一致、可追溯的分析栅格，不直接使用渲染后的彩色云图。按 `arcgis_steps/projection_resample.md` 和 `arcgis_steps/plus_driver_preprocessing.md` 处理 `subsidence_depth_raw.tif`：

- Output Coordinate System、Extent、Snap Raster 和 Cell Size 使用土地利用 master grid；
- 连续深度通常使用 Bilinear；
- 研究区外为 NoData，零下沉与 NoData 分开；
- 输出 `subsidence_depth_aligned.tif`；
- 检查 CRS、像元大小、行列数、范围和像元原点。

## 12. 接入论文第 4.3 节沉陷积水碳储核算

当用户提供同一时期的遥感沉陷积水边界、水面高程和三个碳密度后，使用 `templates/arcgis_module_outputs.json` 中的 `subsidence_water_carbon` 操作。该操作的执行顺序为：

```text
遥感积水边界 + 预采 DEM + DEPTH_M
→ 沉陷后地形与正水深栅格
→ 库容（Σ 水深 × 像元面积）
→ 水体碳 + 水生植被碳 + 底泥碳
→ 沉陷积水复合碳库
```

- `water_boundary` 必须是遥感解译/人工核验的沉陷积水边界，不能以整个矿界或工作面边界替代；
- `water_level_elevation_m` 与 DEM 必须采用同一垂直基准；
- 论文案例按水深阈值推定水生植被面积；本项目要求用户提供本地阈值，或提供实测/解译的 `aquatic_vegetation_mask`；
- 底泥范围优先使用 `bottom_sediment_mask`；如确实假定全水底覆盖，需显式设置 `bottom_sediment_assume_full_waterbed=true`；
- 输出包括水深、水生植被、底泥覆盖栅格，库容 CSV 和三组分碳储 CSV。若同时填写 InVEST 总碳与其沉陷积水面积碳，CSV 会输出替换后的增强总碳，而不是相加后的重复总碳。

## 13. 推荐输出

- 原始 `w.dat` / `w.txt` 只读副本；
- 标准化沉陷点要素；
- `subsidence_depth_raw.tif`；
- `subsidence_depth_aligned.tif`；
- 制图 TIN；
- `subsidence_cloud_clipped.tif`；
- 沉陷边界线和边界面；
- 沉陷等值线和等值线范围面；
- 字段、单位、符号、阈值、分辨率和处理日志。

每个成果名称包含矿名、预计年份和方案 ID。抽查原始点、分析栅格与制图表面数值，确认本流程没有改变外部软件的 W 值含义。
