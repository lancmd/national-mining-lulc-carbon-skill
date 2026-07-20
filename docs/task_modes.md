# 项目任务模式

`project.json` 的 `task_type` 让 MAESA 只验证、编译和运行当前目标所需的模块。手写项目可以省略该字段以兼容旧项目；使用 `build_local_project_from_inputs` 时建议显式填写。

| task_type | 启用模块 | 最小核心输入 |
|---|---|---|
| `classification_only` | ENVI、PyTorch 语义分割或已登记 ResNet-50 图块分类 | 一期或多期影像，加 ROI 或模型包 |
| `lulc_change_analysis` | 30 m 对齐、转移矩阵和 Sankey | 至少两期已有 LULC |
| `plus_only` | PLUS ND/UD/EP/RE | 至少两期已有 LULC、驱动因子；RE 另需沉陷深度或 w.dat |
| `invest_only` | InVEST Carbon 或已配置生态模型 | 已有 LULC、对应碳密度表或模型 datastack |
| `ecosystem_service_only` | Min-Max/AHP、权衡和敏感性 | 指标表和生态服务配置 |
| `mapping_only` | ArcGIS Pro 布局 | APRX、布局和已有结果图层 |
| `full_chain` | 分类、PLUS、InVEST | 多期影像、分类样本/模型、驱动因子、碳密度和 RE 沉陷输入 |

最终布局可以引用工作流中尚未生成的结果，而不是把它伪装成输入文件：

```json
{
  "source": "stage_output",
  "stage_id": "invest_carbon_ND",
  "output_index": 0,
  "name": "自然发展情景碳储量",
  "kind": "continuous"
}
```

编译器会检查 `stage_id` 和 `output_index` 是否对应前序阶段的声明输出；工作流运行到布局阶段前再确认文件实际存在。也可用 `path_scope: "workspace"` 指向已在工作区内生成的成果。
