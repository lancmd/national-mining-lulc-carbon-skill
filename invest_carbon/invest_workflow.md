# InVEST 矿区碳储量计算流程

本模块使用土地利用栅格和用户提供的碳密度表运行 InVEST Carbon Storage and Sequestration，并针对高潜水位煤矿区提供沉陷积水复合碳库的替换核算方法。

## 1. 适用任务

- 多期历史土地利用碳储量计算；
- PLUS 的 ND、UD、EP、RE 情景碳储量比较；
- 矿区生态修复前后固碳增汇评估；
- 沉陷积水扩张造成的陆地碳库损失分析；
- 有水深、植被和底泥数据时的沉陷积水三维碳库核算。

## 2. 两级核算框架

### Level A：标准 InVEST 核算

适用于所有矿区。InVEST 将每个土地利用编码映射到四个碳库密度：

- `c_above`：地上碳；
- `c_below`：地下碳；
- `c_soil`：土壤有机碳；
- `c_dead`：死亡有机质碳。

用户必须提供碳密度，不使用本 Skill 内置默认值。单位统一为 `Mg C/ha`，数值上等同于 `t C/hm²`。

### Level B：沉陷积水增强核算

仅在具备第 4.3 节所需的遥感积水边界、PIM 下沉地形、水体库容、水生植被面积、底泥面积及相应碳密度时使用。增强结果不能直接叠加到 InVEST 总量，而应替换 InVEST 已经计算的沉陷积水基准碳量：

```text
C_total_enhanced
= C_invest_total
- C_invest_subsidence_water
+ C_subsidence_water_composite
```

详见 `invest_carbon/subsidence_water_carbon.md`。

## 3. 输入

### 3.1 土地利用栅格

可使用历史分类图或 PLUS 情景结果，例如：

- `lulc_2000.tif`、`lulc_2005.tif`、`lulc_2010.tif`；
- `lulc_2015.tif`、`lulc_2020.tif`、`lulc_2023.tif`；
- `lulc_2030_ND.tif`、`lulc_2030_UD.tif`；
- `lulc_2030_EP.tif`、`lulc_2030_RE.tif`。

要求：

- 单波段整数 GeoTIFF；
- 使用适合面积计算的投影坐标系；
- 同一比较组的 CRS、范围、像元大小、行列数、Snap 和 NoData 一致；
- 类别编码与 `config/landuse_classes.md` 一致；
- 不在 EPSG:4326 或 Web Mercator 中直接统计平面面积。

### 3.2 碳密度表

InVEST 输入 CSV 至少包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `lucode` | Integer | 与栅格像元值完全一致 |
| `LULC_Name` | Text | 地类名称，便于审计 |
| `c_above` | Float | 地上碳密度，Mg C/ha |
| `c_below` | Float | 地下碳密度，Mg C/ha |
| `c_soil` | Float | 土壤碳密度，Mg C/ha |
| `c_dead` | Float | 死亡有机质碳密度，Mg C/ha |

使用前以当前安装版本的 InVEST 样例表和用户指南为准。不同版本的界面名称、参数键和输出文件名可能变化，不按旧教程硬编码。

模板：

- 普通六类：`templates/invest_carbon_pools_6class.csv`；
- 高潜水位七类：`templates/invest_carbon_pools_7class.csv`。

模板故意不填碳密度，防止空缺被误认为真实的 0。

## 4. 编码覆盖检查

运行前比较栅格有效唯一值与碳密度表 `lucode`：

```text
栅格类别集合 == 碳密度表 lucode 集合
```

若表中多出暂未出现的合法类别，可以保留并说明；栅格中的任何有效类别若在表中缺失，必须停止运行。NoData 与地类 0 必须区分，不能把背景 0 当作合法类别后无意参与计算。

## 5. 碳密度准备

按 `invest_carbon/carbon_density_rules.md` 检查：

1. 单位是否为 Mg C/ha，而不是 CO₂e、g/m² 或 g/m³；
2. 土壤碳密度对应的采样深度是否一致；
3. 地上/地下/土壤/死亡有机质是否重复计量；
4. 水体体积碳是否被错误填入面积碳字段；
5. 每个值是否记录来源、年份、样本量和适用范围；
6. 缺少 `c_dead` 时是否明确决定填 0 并开展敏感性分析。

`c_dead = 0` 表示假设死亡有机质碳为零，不表示“没有数据”。报告中必须披露该假设。

## 6. 运行方式

### 6.1 单期碳储量

选择一幅土地利用图作为 Baseline，关闭碳变化/固碳量和价值量选项，只计算该期碳储量。每个年份使用独立结果后缀和工作空间。

### 6.2 基准与替代情景比较

在支持的当前版本中，可将基期图作为 Baseline、某一未来图作为 Alternate，计算碳储变化。ND、UD、EP、RE 应分别运行，不能把四幅未来图同时混成一个情景。

### 6.3 碳密度随情景变化

标准 InVEST 的一次基准/替代运行通常对同一 `lucode` 使用同一套碳密度。如果未来修复导致单位面积碳密度改变，应分别用各自碳密度表运行单期储量，再在模型外计算差值；不得用一张静态表声称表达了植被生长或底泥年际累积。

### 6.4 价值量

本模块默认只做物质量。只有用户明确提供碳价、基准年、替代年、折现率和价格变化率时才启用价值量；明确区分 `Mg C` 与 `Mg CO₂e`，转换为 CO₂e 时使用 `44/12`，且不得把 CO₂e 值填进碳密度表。

## 7. 结果与版本差异

保存 InVEST 版本、输入文件哈希、参数日志和原始输出。新版 InVEST 已出现 Baseline/Alternate 参数名称、`c_storage`/`c_change` 文件名以及输出单位变化；因此：

- 不依赖固定输出文件名；
- 先读取当前版本生成的 HTML 报告和元数据；
- 确认栅格是 `Mg C/ha` 还是 `Mg C/pixel` 后再汇总；
- 若为 Mg C/ha，逐像元总量需乘像元面积（ha）；
- 不把渲染颜色值当作碳储量。

## 8. 批量结果组织

```text
invest_outputs/
├── historical/
│   ├── 2000/
│   ├── 2005/
│   └── ...
├── scenarios/
│   ├── ND/
│   ├── UD/
│   ├── EP/
│   └── RE/
├── subsidence_water_enhanced/
├── validation/
└── parameters/
```

每个结果目录只对应一次模型运行。不得复用同一目录覆盖不同年份或情景。

## 9. 最终交付

- 各期/各情景碳储量栅格；
- 各地类面积、碳密度和碳储量统计表；
- 基准与情景碳储变化表；
- 沉陷积水增强核算及替换过程（如适用）；
- 碳密度来源与不确定性说明；
- InVEST 版本、参数和验证日志。

结果验收见 `invest_carbon/result_validation.md`。

InVEST 参数名称、输入要求和输出单位以 Natural Capital Project 当前用户指南为准：`https://invest.readthedocs.io/en/stable/`。
