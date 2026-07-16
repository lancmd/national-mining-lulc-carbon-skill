# 从数据文件到本地工作流

智能体可以调用 `build_local_project_from_inputs`，直接用本地路径创建项目，再调用 `run_local_project`。不需要手写 `workflow_job.json`。

最小数据组合如下：

- 至少两期带年份的多波段遥感影像；
- 矿区边界；
- 碳密度 CSV；
- PLUS 驱动因子，其中 DEM 可自动派生坡度和坡向；
- 用户自行由概率积分法或其他预测软件生成的沉陷云图 GeoTIFF（推荐），或 `w.dat`；二者二选一；
- 分类所需的二选一输入：已验证的 PyTorch 模型包，或 ENVI ROI 样本。

构建器会生成 `inputs.imagery_periods`。运行时依次产生每期 LULC、相邻期转移 CSV 和 Sankey SVG、统一网格的驱动因子、ND/UD/EP/RE 请求和输出验证、各情景 InVEST Carbon 结果及其成果清单。每个分类图、PLUS 情景图和 InVEST 栅格还会生成不依赖 `.aprx` 的 SVG 主题图（标题、图例、CRS 和显示分辨率）；如有现成的 ArcGIS Pro 布局，可继续启用 `gis_outputs` 输出出版级 PDF/PNG。

沉陷云图通过 Agent/MCP 的 `subsidence_depth_raster` 输入项提交；它会被检查为正下沉、重采样到 30 m 主网格，并作为 RE 的核心驱动因子。`w.dat` 的坐标被视为最新 LULC 网格的 CRS；若选择该形式，需填写原文件单位和正负约定，并提供工作面或沉陷范围以及最大插值距离。流程将其转换为 `m`、`positive_down`，仅在该范围内补足像元。

水源供给、生境质量和综合生态服务还需要模型参数，而不是单靠遥感影像能够可靠推出。Annual Water Yield 至少需要降水、蒸散、土壤深度/PAWC、分区和生物物理表；Habitat Quality 需要威胁图层、敏感性和可达性参数。项目在没有这些本地 datastack 时会将该部分保持为 `pending_validation`，不会以虚构参数生成图。

官方 PLUS V1.4.2 由本机 GUI 自动化桥接器接收每个情景的请求。桥接器优先使用 pywinauto 控件树，必要时使用经校准的本地截图模板；它会自动接管写入 `outputs/plus/<scenario>/PLUS_<scenario>.tif` 且通过网格检查的结果，但不会把 `prepared` 或 `waiting_interactive` 误报为预测完成。
