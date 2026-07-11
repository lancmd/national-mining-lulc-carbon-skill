# 沉陷积水复合碳库核算

标准 InVEST 按地类平均面积碳密度计算，不能直接表达水体库容变化。本模块按毕佳颖学位论文第 4.3 节的口径，在数据充分时将沉陷积水拆分为水体碳、水生植被碳和底泥碳。

## 1. 使用条件

至少提供：

- 与 PIM 下沉地形同一时期、同一坐标基准的遥感沉陷积水边界；
- 水体库容，或可计算库容的水深/水下地形；
- 水体碳密度（g C/m³）；
- 水生植被覆盖面积和碳密度（Mg C/ha）；
- 底泥覆盖面积和碳密度（Mg C/ha）；
- 各参数来源、时间和不确定性。

只有平面水体面积而没有库容或代表性水深时，不宜声称完成三维水体碳核算；可退回标准 InVEST 面积法并标记限制。

## 2. 组分公式

### 水体碳

```text
C_water_Mg = V_water_m3 × D_water_g_m3 / 1,000,000
```

### 水生植被碳

```text
C_veg_Mg = A_veg_ha × D_veg_Mg_ha
```

### 底泥碳

```text
C_sed_Mg = A_sed_ha × D_sed_Mg_ha
```

### 复合碳库

```text
C_composite_Mg = C_water_Mg + C_veg_Mg + C_sed_Mg
```

模板：`templates/subsidence_water_components_template.csv`。

论文图 4.1 将水样与水生植被归入地上碳、底泥归入土壤碳、地下碳设为 0；但论文后续实际水体碳密度单位为 g/m³。因此本模块采用量纲明确的“库容 × 体积密度”水体公式，不把 g/m³ 直接写成 t/hm²。

## 3. 库容

论文第 4.3.1 节先把遥感提取的积水边界与概率积分法预计的下沉盆地按坐标匹配，再以边界水面高程和逐单元水深计算库容。实现中统一采用正水深：

```text
bed_elevation_m = pre_mining_dem_m - positive_subsidence_depth_m
depth_m = max(water_surface_elevation_m - bed_elevation_m, 0)
volume_m3 = Σ(depth_m × pixel_area_m2)
```

所有高程必须使用同一垂直基准和单位。PIM 下沉等值线只能在已知基准地形、水面高程和边界匹配可靠时参与库容反演；不能把下沉量直接当作水深。

若输入为外部 PIM 软件的 `w.dat`，先使用 `scripts/wdat_to_depth.py` 标准化为正的 `subsidence_depth_m`，再在 ArcGIS Pro 中栅格化和对齐。以正下沉深度为例：

```text
post_mining_elevation = pre_mining_dem - subsidence_depth_m
water_depth = max(water_level_elevation - post_mining_elevation, 0)
water_volume = Σ(water_depth × pixel_area)
```

因此 `w.dat` 能参与库容判断，但还必须有基准 DEM、水面高程、同一坐标与垂直基准以及遥感积水边界；工作面范围只能作为裁剪/约束，不能单独给出库容。`scripts/arcgis_ops.py` 的 `subsidence_water_carbon` 会输出水深栅格、库容表和三组分碳表。

## 4. 水生植被面积

论文第 4.3.2 节以主断面 GPS/水下相机调查确定临界水深；其五沟煤矿案例中，水深大于 1.2 m 的区域不发生自然水生植被。因此自动模式按下式给出**潜在**水生植被面积：

```text
A_veg = A_water - A(depth > local_threshold_m)
```

该阈值具有物种和场地依赖性，论文案例的 1.2 m 不能作为全国默认值。若用户提供实测或遥感解译的水生植被边界，执行器优先采用该边界；否则输出必须标记为 `potential`，并用实测/影像验证。

若用遥感直接分类植被覆盖，应说明季节、传感器、精度和是否包含漂浮/挺水/沉水植被。植被面积不得超过水体面积。

## 5. 底泥面积

底泥面积应来自测量、沉积范围解释或明确假设。不能默认等于水体面积；论文案例中底泥覆盖面积甚至可与某期水面植被面积不同，必须独立记录。若确实以全水底作为底泥覆盖范围，必须显式设置 `bottom_sediment_assume_full_waterbed=true`，输出表会记录该假设。

底泥碳密度应说明取样深度、容重、有机碳含量和是否按干重计算。

## 6. 与 InVEST 合并：替换而非叠加

先计算 InVEST 中沉陷积水基准碳量：

```text
C_invest_subsidence_water_Mg
= A_subsidence_water_ha
× (c_above + c_below + c_soil + c_dead)
```

再执行：

```text
C_total_enhanced_Mg
= C_invest_total_Mg
- C_invest_subsidence_water_Mg
+ C_composite_Mg
```

若只需要报告沉陷积水内部三个组分，也可并列展示标准 InVEST 面积法和增强法，但不能把两者相加。

## 7. 论文案例参数

论文五沟煤矿案例报告：水体碳密度 26.25 g C/m³、水生植被碳密度 0.46 t C/hm²、底泥碳密度 62.42 t C/hm²；用 2023 年 71.51 万 m³、44.57 hm²、51.28 hm²代入可复现约 3240.17 t C。这些值仅用于理解公式或复现论文，不能作为其他矿区默认值。

## 8. 不确定性

至少对以下变量设置低/中/高情景：

- 水体边界与库容；
- 水体碳浓度的季节变化；
- 水生植被覆盖面积与碳密度；
- 底泥覆盖范围、深度和碳密度。

报告各组分对总量的贡献和敏感性。若底泥占比极高，应重点检查面积、采样厚度和单位换算。
