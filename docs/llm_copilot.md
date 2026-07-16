# MAESA Copilot

MAESA 不是自行训练或托管模型权重的项目。它是一个把 LLM 理解能力、矿区研究规则与本地 GIS 工具连接起来的 Agent 产品：模型负责理解目标、检查缺失输入和调用工具；ArcGIS Pro、ENVI、PLUS 与 InVEST 始终保留在用户电脑本地运行。

## 两种使用方式

### 1. 直接作为 Codex / Claude / 国产 Agent 的 Skill

安装 Skill 并配置本地 MCP 后，宿主 Agent 本身就是 LLM。MAESA 提供专业提示、项目配置、数据契约和本地工具；不需要在仓库中重复部署另一个模型。

### 2. 可选的独立 Copilot

复制 `config/llm_provider.example.json` 为本机忽略的 `config/llm_provider.json`。默认示例面向本地 Ollama：

```powershell
Copy-Item .\config\llm_provider.example.json .\config\llm_provider.json
python .\scripts\maesa_copilot.py --message "检查我的矿区项目需要哪些输入" --dry-run
```

安装并启动 Ollama、拉取自己选定的模型后，可移除 `--dry-run`：

```powershell
python .\scripts\maesa_copilot.py --message "为 2020 到 2025 年矿区变化分析制定本地执行计划" --project .\project.json
```

`openai_compatible` 可连接任意兼容 Chat Completions 的服务。远程模型端点需要在配置中显式写入 `allow_cloud: true`；这只允许文本请求离开本机，绝不允许远程控制本地 GIS 软件。

## 边界

- Copilot 默认只生成建议和本地 MCP 调用顺序，不会擅自执行模型或覆盖成果；
- 真实运行仍由 `validate_local_project`、`compile_project_workflow` 和 `run_local_project` 经过本地 MCP 完成；
- 影像、矿区边界、碳密度、沉陷数据和软件窗口不会自动上传给云端模型；
- 没有 API Key、Ollama 或可用模型时，MAESA 仍可作为 Codex Skill 使用。
