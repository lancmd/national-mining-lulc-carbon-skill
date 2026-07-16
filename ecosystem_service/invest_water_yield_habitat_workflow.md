# 水源供给与生境质量自动计算

本模块把每期 LULC 或 PLUS 情景 LULC 分别传入本地 InVEST Annual Water Yield 和 Habitat Quality。每次运行使用独立工作目录；输出随后进入情景比较、权衡分析、Min-Max 或 AHP 综合评价。

## 水源供给

Annual Water Yield 的像元值是年产水深度。项目汇总阶段会按像元面积把有效像元的 mm 转换为 m³；不能直接把水深像元值相加。

高潜水位采煤沉陷区可用沉陷积水进行校准：从遥感影像提取沉陷积水边界，以 PIM `w.dat` 生成的沉陷深度与 DEM 叠加得到沉陷后地形，按统一水面高程计算积水库容/径流体积，再与 InVEST 年产水量比较，选择误差可接受的季节常数 `Z`。校准记录应保存候选 Z、观测/反演体积、InVEST 体积、相对误差和选定值。

Annual Water Yield datastack 至少要包含：

- `lulc_path`：本工作流生成的 LULC；
- `precipitation_path`：对应年份年降水 GeoTIFF，mm；
- `eto_path`：对应年份参考蒸散 GeoTIFF，mm；
- `depth_to_root_rest_layer_path`：根系限制层深度 GeoTIFF，mm；
- `pawc_path`：植物可利用含水量 GeoTIFF，0–1；
- `watersheds_path`：流域/汇水区矢量；
- `biophysical_table_path`：至少含 `lucode`、`root_depth`、`Kc` 和 `lulc_veg`；
- `seasonality_constant`：经校准或有明确依据的正数 Z。

同一年内，降水、ET0、LULC、土壤层和流域应统一到同一投影、范围、像元网格。若水文计算涉及面积或体积，使用米制投影坐标系。

## 生境质量

Habitat Quality 以 LULC 的生境适宜性、威胁源影响和各地类对威胁的敏感性计算 0–1 指数。项目会把每期/每情景栅格按有效像元做面积加权平均；空间评价仍保留原始生境质量栅格。

Habitat Quality datastack 至少要包含：

- `lulc_cur_path`：本工作流生成的 LULC；
- `threats_table_path`：至少含 `threat`、`max_dist`、`weight`、`decay`、`cur_path`；
- 每个 `cur_path` 指向同一时期的威胁栅格，例如建设用地、道路、铁路、采场/排土场或夜间灯光；
- `sensitivity_table_path`：至少含 `lulc`、`habitat`，并为 threats 表每个威胁提供敏感性列；
- `half_saturation_constant`：有明确生态学依据的正数；
- 可选 `access_vector_path`：保护地或可达性修正面。

每个威胁栅格的年份、距离单位和衰减类型都要记录。威胁范围不是由道路距离栅格自动推断的；需要提供威胁源栅格或原始矢量，以及研究者确认的最大影响距离、权重和敏感性。

## 自动检查与输出

运行非 Carbon InVEST 前，`invest_ecosystem_contract.py` 会检查 datastack、参数表关键字段和本地文件是否存在。检查不通过时流程停止，不产生伪造的水源供给或生境质量图。

输出包括：

- 各期/各情景 Annual Water Yield 栅格与 m³ 汇总；
- 各期/各情景 Habitat Quality 栅格与平均指数；
- 校准记录（若启用沉陷积水校准）；
- 水源供给、生境质量、碳储量的权衡/协同与综合生态服务结果；
- 自动 SVG 专题图，以及可选 ArcGIS Pro 布局图。
