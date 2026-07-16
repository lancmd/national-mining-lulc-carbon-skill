# MAESA Copilot

MAESA Copilot 可以使用本地 Ollama 或兼容 Chat Completions 的模型理解研究目标；GIS 软件、MCP 服务和数据始终留在本机。远程模型仅接收用户允许发送的文字请求，不能获得 ArcGIS Pro、ENVI、PLUS 或 InVEST 的远程控制通道。

## 两种运行方式

- 在 Codex、Claude 或其他支持 MCP 的 Agent 中，宿主 Agent 负责推理并调用 MAESA 的本地工具。
- `scripts/maesa_copilot.py` 是可选的独立 Copilot。它可以生成受约束的执行计划，并通过本地 stdio MCP 服务执行该计划。

独立 Copilot 不执行自由文本中的命令。它只接受固定的本地工具顺序：能力检查、项目校验、工作流编译、项目运行和结果验收。执行计划会校验 `schemas/maesa_execution_plan.schema.json` 的字段，并再次核对项目路径、工具顺序与每一步参数。

## 确认式执行

先生成并检查计划：

```powershell
Copy-Item .\config\llm_provider.example.json .\config\llm_provider.json
python .\scripts\maesa_copilot.py --project .\project.json `
  --message "运行本项目并生成已配置成果" `
  --write-execution-plan .\runtime\execution_plan.json
```

输出会列出预计输入、阶段、成果清单和确认要求。确认无误后再运行：

```powershell
python .\scripts\maesa_copilot.py --execute-plan .\runtime\execution_plan.json --confirm
```

运行中遇到 `waiting_interactive`、`prepared` 或 `pending_validation` 时，Copilot 会停止并返回同一计划的续跑提示；它不会跳过 PLUS 校准、UAC、缺失数据或地图视觉验收。修正本地问题后，用同一条带 `--confirm` 的命令续跑即可，工作流会接管已完成的成果。

不希望调用 LLM 时，可先预览确定性计划：

```powershell
python .\scripts\maesa_copilot.py --provider .\config\llm_provider.json `
  --project .\project.json --message "预览" --dry-run
```
