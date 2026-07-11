# 矿区 GIS 后端协议 v1

本协议把智能体工具与具体软件解耦。MCP 服务只发送结构化任务；ArcGIS、ENVI、PLUS、GEE、InVEST 或开放 GIS 后端分别实现桥接器。软件可位于本机、局域网服务器、云端容器或桌面插件中，不要求与智能体安装在同一路径。

## 请求

```json
{
  "protocol_version": "1.0",
  "request_id": "uuid",
  "operation": "envi.supervised_classification",
  "parameters": {},
  "callback_url": null
}
```

后端必须接受 UTF-8 JSON。HTTP 后端使用 `POST`；socket 后端使用一行一个 JSON 对象；command 后端从标准输入读取一个 JSON 对象并把响应写到标准输出。

## 响应

```json
{
  "protocol_version": "1.0",
  "request_id": "uuid",
  "status": "completed",
  "job_id": "backend-job-id",
  "message": "",
  "outputs": [],
  "metrics": {},
  "error": null
}
```

允许状态：

- `accepted`：后端已接收异步任务；
- `running`：任务正在执行；
- `completed`：执行成功且输出已生成；
- `pending_validation`：产物存在但仍需独立验证；
- `waiting_interactive`：软件要求登录、授权或 GUI 操作；
- `failed`：任务失败，`error` 必须说明原因；
- `cancelled`：任务已取消。

`prepared` 只能用于生成脚本或模型包，不能冒充软件已执行。

## 标准操作

| operation | 后端 | 必要参数 |
|---|---|---|
| `system.capabilities` | 所有 | 无 |
| `system.job_status` | 所有 | `job_id` |
| `system.cancel_job` | 所有 | `job_id` |
| `system.list_outputs` | 所有 | `job_id` |
| `dataset.inspect` | 任意 GIS | `path` |
| `gee.export_imagery` | GEE | `template`, `variables`, `destination` |
| `envi.supervised_classification` | ENVI | `input_raster`, `training_vector`, `output_raster`, `method` |
| `arcgis.run_operations` | ArcGIS | `spec`, `workspace` |
| `plus.run_scenario` | PLUS | `project`, `scenario` (`ND`/`UD`/`EP`/`RE`), `workspace`; `RE` additionally requires `parameters.resource_extraction` |
| `invest.run_carbon` | InVEST | `datastack`, `workspace` |
| `pytorch.validate_model` | PyTorch | `model_package` |
| `pytorch.run_lulc_inference` | PyTorch | `model_package`, `input_raster`, `class_output`, `confidence_output` |
| `project.validate` | Project validator | `project_file` |
| `ecosystem.evaluate` | Local ecosystem evaluator | `criteria_table`, `config`, `output` |

后端可扩展操作，但必须在 `system.capabilities` 中返回名称、参数模式、软件版本和限制。

`arcgis.run_operations` 支持 `subsidence_water_carbon`：该操作以遥感沉陷积水边界、预采 DEM、正下沉深度、同一垂直基准的水面高程和用户碳密度为输入，输出水深栅格、库容表、水生植被/底泥覆盖栅格及三组分碳表。它不接收彩色云图作为数值输入。

### PLUS 资源开采情景（RE）参数契约

项目默认 PLUS 情景为 `ND`、`UD`、`EP`、`RE`。调用 `RE` 时，`parameters.resource_extraction` 必须至少包含：

```json
{
  "core_driver": "subsidence_depth",
  "subsidence_depth_raster": "D:/project/intermediate/subsidence_depth_aligned.tif",
  "depth_unit": "m",
  "depth_convention": "positive_down",
  "additional_driver_factors": ["dem", "slope", "road_distance", "mine_distance"]
}
```

`subsidence_depth_raster` 是由外部概率积分法软件输出的 `w.dat`/`w.txt` 或等价结果，经单位、符号、地理参考核验、栅格化并对齐 PLUS 主网格后的连续数值栅格。它是 RE 的核心驱动因子，但不替代 DEM、地形、区位、社会经济、工作面或开采规划等其他因素。原始 `w.dat`、彩色沉陷云图和等值线图不能直接传给 PLUS；本项目也不计算概率积分法下沉值。

软件插件可直接实现 socket 协议，也可用 `scripts/bridge_server.py --handler package.module:handle --port <端口>` 暴露一个 Python `handle(request) -> response` 函数。GEE/PLUS 的服务化后端通常使用 HTTP；QGIS、ArcGIS、ENVI 等桌面进程通常使用 socket 或软件插件；容器与命令行工具可使用 command transport。

## 安全与复现

- 后端不得覆盖源数据，除非请求显式设置 `overwrite_source=true`。
- 返回绝对输出路径或可访问的对象存储 URL。
- 记录软件版本、输入摘要、参数、开始/结束时间和日志位置。
- 地理处理必须返回 CRS、像元大小、范围、NoData 和分类值域等验证信息。
- 认证令牌只通过后端环境变量或密钥服务读取，不得写进任务清单与响应。
