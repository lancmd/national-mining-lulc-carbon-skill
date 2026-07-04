---
name: national-mining-lulc-carbon-skill
description: 全国矿区土地利用分类、沉陷积水识别、PLUS模型预测、InVEST碳储量估算和生态服务价值评价全流程 Skill，适用于煤矿、金属矿、非金属矿、废弃矿山和生态修复矿区。
---

# 全国矿区土地利用—碳储量—生态服务评估 Skill

## 1. 适用范围

本 Skill 适用于全国不同类型矿区，包括煤矿区、金属矿区、非金属矿区、历史遗留矿山修复区、采煤沉陷区和高潜水位矿区。主要用于土地利用分类、沉陷积水识别、土地利用变化分析、PLUS 模型预测、InVEST 碳储量计算和生态服务价值评价。

## 2. 用户输入参数

使用本 Skill 前，需要用户提供以下信息：

- 研究区边界：shp、geojson 或 GEE asset；
- 研究年份：如 2000、2005、2010、2015、2020、2025；
- 矿区类型：煤矿、金属矿、非金属矿、废弃矿山；
- 地貌类型：平原矿区、山地丘陵矿区、干旱半干旱矿区、高潜水位矿区；
- 分类体系：默认六类，可根据矿区类型调整；
- 是否考虑沉陷积水：是 / 否；
- 是否开展 PLUS 模拟：是 / 否；
- 是否开展 InVEST 碳储量计算：是 / 否；
- 是否开展生态服务价值评价：是 / 否。

## 3. 数据源选择规则

### 遥感影像

- 2000—2011：优先使用 Landsat 5；
- 2013—至今：优先使用 Landsat 8/9；
- 2017—至今：优先使用 Sentinel-2；
- 高潜水位煤矿区水体提取优先使用 NDWI、MNDWI，并结合矿区边界和历史影像进行人工校正。

### 地形数据

- DEM：SRTM 30m 或 ASTER GDEM 30m；
- 坡度、坡向：由 DEM 派生。

### 气候数据

- 年平均气温：WorldClim 或 TerraClimate；
- 年平均降水：WorldClim 或 TerraClimate。

### 社会经济数据

- 人口密度：WorldPop；
- GDP：RESDC、GeoData 或公里网格 GDP；
- 道路、铁路、河流：OpenStreetMap。

## 4. 默认土地利用分类体系

### 普通矿区六类

1. 水体
2. 建设用地
3. 耕地
4. 林地
5. 草地
6. 裸地/工矿用地

### 高潜水位煤矿区增强七类

1. 沉陷积水
2. 自然水体
3. 建设用地
4. 耕地
5. 林地
6. 草地
7. 裸地/工矿用地

### 分类规则

- 光伏板默认并入建设用地；
- 采场、排土场、裸露地表可并入裸地/工矿用地；
- 高潜水位煤矿区应尽量区分沉陷积水和自然水体；
- 金属矿、非金属矿一般不强制区分沉陷积水。

## 5. 工作流程

### Step 1：研究区和年份确定

根据用户提供的矿区边界和研究年份，判断适合的遥感数据源和空间分辨率。

当 GEE 目录不能满足数据获取、需要固定具体产品版本或开展多矿区批处理时，读取 `open_gis_workflows/data_discovery.md`，使用官方目录/STAC 搜索并保存产品 ID、访问日期和许可。

### Step 2：影像下载与预处理

根据年份自动选择 Landsat 或 Sentinel-2 数据，完成去云、合成、裁剪和指数计算，输出分类输入影像。常用指数包括 NDVI、NDWI、MNDWI、NDBI。

按任务读取并修改对应的 GEE 模板：

- Landsat 分类输入：`gee_codes/landsat_lulc_input.js`；
- Sentinel-2 分类输入：`gee_codes/sentinel2_lulc_input.js`；
- 月尺度水体指数：`gee_codes/ndwi_monthly_download.js`；
- DEM 与坡度：`gee_codes/dem_slope_download.js`；
- WorldClim 静态气候背景：`gee_codes/climate_download.js`；
- WorldPop 人口数量与密度：`gee_codes/population_download.js`。

运行前必须替换 `roiAsset`，并按研究区设置年份、月份、云量阈值和投影坐标系。运行后先检查控制台影像数量与输出波段，再在 Tasks 面板启动导出任务。

需要在服务器或本地批量处理多年份、多矿区数据时，读取 `open_gis_workflows/gdal_batch_processing.md`；不得用 GDAL 命令行替换已经稳定且规模较小的桌面流程。

### Step 3：土地利用分类

根据用户需求，提供 ENVI 监督分类、ArcGIS 随机森林、GEE 随机森林或深度学习分类流程。分类完成后统一输出 GeoTIFF。

开展 ENVI 分类时，按需读取：

- `envi_classification/supervised_classification.md`：分类器选择、参数与后处理；
- `envi_classification/roi_sample_rules.md`：训练样本和验证样本规则；
- `envi_classification/accuracy_assessment.md`：独立精度评价；
- `envi_classification/export_to_arcgis.md`：分类结果导出和网格检查。

至少比较一个机器学习分类器与一个传统分类器；用户提出“最大最小分类”时，分别运行最大似然法和最小距离法，并使用同一独立验证集比较，不把二者混写为单一算法。

### Step 4：面积统计与土地利用转移

统计各年份土地利用面积，统一换算为 hm²。利用 ArcGIS Pro 的 Combine 或 Tabulate Area 工具计算土地利用转移矩阵，并整理 Sankey 图数据。

先读取 `arcgis_steps/projection_resample.md` 统一分析坐标系和主网格，再按 `arcgis_steps/area_statistics.md` 统计面积。不得在 EPSG:4326 或 Web Mercator 中直接进行平面面积统计，也不得用各期总面积反推转移矩阵。

### Step 5：PLUS 模型预测

准备 DEM、坡度、气温、降水、土壤、人口、GDP、道路距离、铁路距离、河流距离、矿区距离等驱动因子。设置自然发展、生态保护和矿区开发等情景，预测未来土地利用格局。

读取 `arcgis_steps/plus_driver_preprocessing.md`，以基期土地利用图为 master grid，统一所有驱动因子的 CRS、像元、范围、行列数、Snap 和 NoData；只有 DEM 时，用 Surface Parameters 派生坡度和坡向，用 Distance Accumulation 生成道路、铁路、河流、城镇和矿区距离栅格。

随后按以下顺序读取 PLUS 模块：

- `plus_model/plus_workflow.md`：总体流程、LEAS/CARS、土地需求和结果验收；
- `plus_model/driver_factors.md`：驱动因子选择、时间匹配和共线性检查；
- `plus_model/calibration_validation.md`：历史回代、FoM/Kappa 和多随机种子；
- `plus_model/scenario_setting.md`：ND、UD、EP、RE 四情景；
- `plus_model/conversion_rules.md`：转换矩阵语义和可达性；
- `plus_model/pim_subsidence_driver.md`：外部 PIM 软件结果与资源开采情景的接口。

未来预测前必须完成已知年份回代。Kappa 不能单独作为通过依据，应同时报告 FoM、关键地类精度和多随机种子稳定性。论文或附件中的百分比只能作为案例参数或敏感性分析起点，不得作为全国矿区固定默认值。资源开采情景只接收独立沉陷预计软件导出的 `w.dat`、`w.txt` 或栅格；本 Skill 不计算 PIM 或预测 W 值，但可用已有 W 点生成 GIS 沉陷云图、边界和等值线，并输出 PLUS 对齐栅格。PIM 下沉深度不等于沉陷积水。

### Step 6：碳储量计算

基于 InVEST 模型计算地上碳、地下碳、土壤碳和死有机质碳。若研究对象为沉陷积水矿区，应额外考虑水体碳、水生植物碳和底泥碳，构建沉陷积水复合碳库。

### Step 7：生态服务价值评价

采用 Max-Min 标准化和 AHP 层次分析法，构建矿区生态服务价值评价体系，综合评价碳储量、水源涵养、生态质量、建设干扰和修复潜力。

## 6. 输出规范

根据用户需求输出：

- GEE 下载代码；
- ArcGIS Pro 操作步骤；
- ENVI 分类建议；
- 土地利用面积统计表；
- 土地利用转移矩阵；
- Sankey 图数据格式；
- PLUS 驱动因子清单；
- PLUS 情景设置说明；
- InVEST 碳密度表；
- 沉陷积水复合碳库计算方案；
- 生态服务价值评价指标体系；
- 论文方法段落；
- 汇报 PPT 文本。

## 7. 注意事项

- 所有栅格数据在进入 PLUS 模型前应统一坐标系、分辨率、范围和行列数；
- 分类结果应进行精度评价，至少包括总体精度和 Kappa 系数；
- 土地利用转移矩阵不能只根据总面积反推，应由两期分类图叠加得到；
- 沉陷积水与自然水体不能仅靠 NDWI 区分，应结合矿区边界、沉陷区范围、历史影像和人工判读；
- 碳储量计算中，沉陷积水不宜简单套用普通水体碳密度，应考虑水体碳、水生植物碳和底泥碳。
- 交付任何模型输入或空间分析成果前，读取 `open_gis_workflows/validation_and_manifest.md`，完成技术验证并填写 `templates/data_manifest.json`；没有独立分类验证样本时，将分类精度状态标记为 pending，不中断其他技术处理。
