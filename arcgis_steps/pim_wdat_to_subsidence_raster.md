# ArcGIS Pro：将 PIM 点数据转为沉陷栅格

本流程将带坐标的 `w.dat`、`w.txt` 或 CSV 转换为沉陷深度栅格、可选风险分级和 PLUS 对齐驱动。

## 1. 输入审计

确认文件至少包含 `X`、`Y`、`W`，并记录 CRS、坐标单位、W 单位、正负号、预计年份、工作面 ID 和网格间距。若没有坐标、仿射变换或明确的行列网格定义，应停止空间转换并向 PIM 输出方补充信息。

检查 X/Y 是否落在研究区附近、点间距是否规则、是否存在重复坐标或空值、W 是累计下沉还是速率，以及下沉为正还是为负。

## 2. 导入点

ArcGIS Pro 路径：`Analysis → Tools → XY Table To Point`。

- X Field：`X`；
- Y Field：`Y`；
- Coordinate System：输入坐标真实 CRS，不是地图当前 CRS；
- 输出优先使用 File Geodatabase，要跨软件交换时可使用 GeoPackage。

导入后叠加矿区边界、工作面和道路检查位置。位置不正确时先排查经纬度顺序、带号、假东移、坐标单位和 CRS，不能用“定义投影”移动数据。

## 3. 统一深度字段

新增 Double 字段 `DEPTH_MM`。根据已确认的符号和单位计算：

- W 为负值且单位 mm：`DEPTH_MM = -W`；
- W 为正值且单位 mm：`DEPTH_MM = W`；
- W 为 m：先乘 1000。

不要无条件使用 `Abs(W)`，否则会把真实抬升或异常值误当作下沉。

## 4. 生成栅格

### 规则点网格

使用 `Conversion Tools → To Raster → Point to Raster`：Value field 选 `DEPTH_MM`，Cell size 采用原始 PIM 网格间距。先保存原始网格版本，不强行直接变为 PLUS 分辨率。

### 非规则点

可测试 Natural Neighbor、IDW 或 Kriging。用独立点或交叉验证选择方法，报告 MAE/RMSE 和参数；不得仅根据云图是否“平滑”选择。限制插值范围，避免跨越无开采影响区域外推。

## 5. 对齐 PLUS 主网格

按 `arcgis_steps/projection_resample.md` 和 `arcgis_steps/plus_driver_preprocessing.md` 处理：

- Output Coordinate System、Extent、Snap Raster、Cell Size 均使用基期土地利用图；
- 连续深度通常用 Bilinear；风险等级用 Nearest；
- 研究区外设 NoData，研究区内零下沉与 NoData 必须区分；
- 最终检查 CRS、像元大小、行列数、范围和像元原点。

## 6. 风险分级（可选）

只有获得本地阈值依据后才运行 `Spatial Analyst → Reclass → Reclassify`。附件中的示例是：

| 深度（mm） | 示例等级 |
|---|---|
| 0—100 | 1 |
| 100—300 | 2 |
| 300—600 | 3 |
| ≥600 | 4 |

边界包含关系需在重分类表中明确。该阈值不是全国统一标准，应根据地质、地下水、地表设施和历史积水校准。

## 7. 等值线与制图

使用 `Spatial Analyst → Surface → Contour` 从连续深度生成等值线。等值距依据数据范围和地图比例尺确定，不固定为 100 mm。等值线用于展示，不应反向替代原始栅格作为模型输入。

## 8. 积水易发性

下沉栅格不能直接视为未来水体。若数据允许，应叠加沉陷后高程、地下水位、闭合洼地、排水和历史积水，构建 `waterlogging_susceptibility.tif`；若条件不足，输出名使用 `subsidence_influence.tif`，并注明不代表确定积水。

## 9. 输出验收

- `pim_points.gdb` 或 GeoPackage；
- `subsidence_depth_raw.tif`；
- `subsidence_depth_aligned.tif`；
- `subsidence_risk.tif`（可选）；
- `subsidence_contour`；
- 输入字段、符号、单位、插值和对齐日志。

进入 PLUS 前抽查原始点处栅格值，确认量级、方向和空间位置一致。
