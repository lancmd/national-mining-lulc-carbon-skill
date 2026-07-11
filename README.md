# Intelligent Agent for Mining Area Ecological Space Analysis

面向矿区土地利用、PyTorch/ENVI 分类、PLUS 情景模拟和 InVEST 碳储量分析的跨软件执行型 Skill。整体采用“MCP 工具层 + 软件桥接层”：智能体调用稳定工具协议，GEE、PyTorch、ArcGIS Pro、ENVI、PLUS、InVEST、QGIS 或开放 GIS 可位于本机、服务器或云端，不依赖固定安装路径。

## 快速开始

```powershell
Copy-Item interfaces/backend_registry.example.json interfaces/backend_registry.json
python -m pip install -e mcp_server
mining-gis-mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

需要运行本地 PyTorch 分类时安装可选依赖：

```powershell
python -m pip install -e "mcp_server[pytorch]"
```

默认 MCP 地址为 `http://127.0.0.1:8765/mcp`。在 `interfaces/backend_registry.json` 中注册实际后端：HTTP 可接 GEE/PLUS 服务，socket 可接软件内部插件，command 可接当前 ArcPy/InVEST 本地适配器。没有 MCP 客户端时，仍可使用 `scripts/workflow_agent.py` 作为本地兜底。

## 本地项目主流程

以 `templates/local_project.json` 建立项目：用户提供本地遥感影像、ROI、矿区边界、碳密度、PLUS 驱动因子，以及可选训练 ROI、PyTorch 模型、DEM、`w.dat`/沉陷深度和生态服务指标表。先执行：

```powershell
python scripts/project_validator.py --project <project.json>
```

再按项目设置选择 ENVI 或 PyTorch 分类，运行 PLUS、InVEST、沉陷积水库容和 Min-Max/AHP 生态服务。PLUS 默认输出 ND（自然发展）、UD（城镇发展）、EP（生态保护）、RE（资源开采）四种情景；RE 以外部概率积分法结果转换并对齐后的正下沉深度 TIF 为核心驱动，同时保留其他驱动因子。每个空间结果最终通过 ArcGIS Pro 布局导出 PDF/PNG。

## 目录

- `scripts/`：执行器和软件适配脚本。
- `deep_learning/`：PyTorch 模型包、推理和精度控制规范。
- `mcp_server/`：智能体可调用的统一 MCP 工具服务。
- `interfaces/`：软件桥接协议与后端注册表。
- `execution/`：执行契约与后端能力边界。
- `templates/`：任务清单和 ArcGIS 操作清单模板。
- `config/`：分类体系、数据源和矿区类型规则。
- `gee_codes/`、`envi_classification/`、`arcgis_steps/`、`plus_model/`、`invest_carbon/`：领域流程与参数依据。
- `open_gis_workflows/`：开放 GIS 数据与验证规范。

常用本地模板：`templates/local_project.json`、`templates/arcgis_module_outputs.json`、`templates/ecosystem_service_config.json`。沉陷积水库容必须使用基准 DEM、正下沉深度栅格和水面高程；`w.dat` 先标准化为下沉深度，不能直接当水深。

源数据默认只读，派生文件写入任务自己的 `workspace`。
