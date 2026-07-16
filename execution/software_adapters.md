# 软件适配器

## 本地接入模型

本项目把 MCP 当作本地进程间的工具协议，而不是软件控制网络。MCP 服务、桥接器和目标软件运行在同一台机器上；连接方式限于本地命令、回环 socket 或回环 HTTP。`interfaces/backend_protocol.md` 规定了请求、状态和产物格式，`interfaces/backend_registry.json` 记录本机已启用的后端。

每个后端通过 `system.capabilities` 说明软件版本、可用操作、许可状态和限制。Agent 依据这份能力信息选择路径，而不是猜测安装位置或命令参数。个人路径通过环境变量或 `config/local_paths.example.json` 配置，不进入共享项目文件。

## ArcGIS Pro

本地 ArcGIS 适配器通过 `propy.bat` 调用 `scripts/arcgis_ops.py`。它可以处理投影、重采样、掩膜裁剪、坡度坡向、距离栅格、属性表、面积统计、转移组合和沉陷积水复合碳库。分类栅格采用 `NEAREST`，连续栅格通常采用 `BILINEAR`；同一分析任务使用一致的 `snapRaster`、`cellSize`、`extent` 和 `mask`。

`export_layout` 用于直接导出已有布局；`compose_layout` 则从 `.aprx` 副本出发，将任务列出的成果图层加入目标地图，应用 `.lyrx` 符号，更新标题和地图范围，并导出 PDF/PNG 与布局验证 JSON。任务应给出布局、地图框、图例和符号规则。自动检查覆盖图层、图例元素、范围和分辨率；颜色、标签、顺序和遮挡仍需通过导出图进行视觉复核。

## InVEST

InVEST 通过本机 CLI 或本机容器运行 datastack。模型工作目录与项目工作目录分开保存，便于排查和复跑。完成后读取 InVEST 日志和版本对应的产物，并用像元面积与碳密度进行数量级检查；需要比较时，可将结果与独立的标准 InVEST 运行结果逐栅格或逐汇总表核对。

## ENVI

ENVI 后端由 `scripts/envi_backend.py` 通过本机 IDL 命令直接调用，不再依赖需要另行启动的 9882 socket 服务。配置 `IDL_EXE` 或 `config/local_paths.json` 的 `idl` 后，`envi.supervised_classification` 可运行最大似然或最小距离分类。最大似然和最小距离分类共享同一套训练/验证样本后再比较精度；未安装、未授权或需要本机登录时，后端会如实返回 `failed` 或 `waiting_interactive`。

## PyTorch

PyTorch 后端提供 `pytorch.validate_model` 和 `pytorch.run_lulc_inference`。模型包包含哈希、类别、波段、归一化和 patch 参数，优先采用 `.pt2` ExportedProgram。推理使用重叠分块融合，输出分类和置信度 GeoTIFF。没有独立验证样本时，结果状态为 `pending_validation`；验证报告记录 OA、F1、IoU 和各类别精度。

## PLUS

PLUS 的自动化入口因发布版本而异，因此 `plus.run_scenario` 由与本机 PLUS 版本匹配的桥接器实现。桥接器可以是本地 GUI 插件、宏、进程控制脚本或进程内 API，并在能力响应中公开支持的参数模式。

PLUS 使用固定的 HPSCIL 官方仓库快照。`scripts/plus_v142_gui_bridge.py` 会校验官方 origin、固定提交、仓库内 EXE 名称和 SHA-256；随后以 pywinauto 控件树优先、经校准截图模板后备的方式执行本地 GUI。该仓库无 Release/Tag，EXE 文件名与实际 UI 标题版本不一致，桥接器会记录两者而不将任一标签伪装为已证实版本。ND、UD、EP、RE 各有独立请求、状态和输出目录。未完成 UI 校准、程序仍在计算或输出尚未通过网格验证时返回 `waiting_interactive`。详见 `docs/plus_v142_gui_automation.md`。

桥接器不存在时，项目后端仍可完成输入对齐、情景参数整理和任务包生成，状态为 `prepared`。若 PLUS 需要用户在本机界面确认，则返回 `waiting_interactive`。这两种状态都不表示 PLUS 已完成预测。完成的后端还应返回每个随机种子的输出、FoM、关键地类精度和稳定性统计。

## 开放 GIS 工具

GDAL、QGIS、GeoPandas 和 rioxarray 可承担本地等价批处理。替换某个步骤前，应检查分类值未被插值、目标 CRS 合理、像元网格与主栅格对齐，并保存命令与版本信息。
