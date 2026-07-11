# 生态服务评价执行模块

本模块以用户或前序模型生成的本地指标表为输入，执行 Min-Max 标准化或 AHP 权重评价。它不自行把没有空间依据的指标编造成生态服务数据。

## 输入

指标 CSV 至少包含一个空间单元 ID 和配置文件列出的指标，例如：

```text
unit_id,carbon_storage,water_regulation,habitat_quality,disturbance
```

每行可以是矿区分区、网格、土地利用地类或情景。栅格型指标应先在 ArcGIS Pro 中按同一网格或分区统计，避免把不同范围的统计值直接混合。

## Min-Max

对效益型指标：

```text
score = (x - min) / (max - min)
```

对成本型指标：

```text
score = (max - x) / (max - min)
```

常数指标记为 0.5，表示对排序没有区分度。权重会自动归一化。

## AHP

AHP 读取成对比较矩阵，计算特征向量权重和一致性比率 CR。默认要求 `CR <= 0.10`；超过阈值时拒绝输出总分，要求调整判断矩阵。

运行：

```powershell
python scripts/ecosystem_service.py --criteria-table <指标.csv> `
  --config templates/ecosystem_service_config.json --output <结果.csv>
```

## ArcGIS Pro 图件

将输出分数表按 `unit_id` 连接回矢量分区，或把同一网格的分数 CSV 转栅格。最终使用 `arcgis_ops.py` 的 `export_layout` 导出 PDF/PNG；每幅图要显示年份、情景、坐标系、比例尺、图例和数据来源。
