---
name: mining-area-ecological-space-analysis
description: 在本机执行矿区遥感土地利用分类、PLUS ND/UD/EP/RE 情景预测、InVEST 碳储量、沉陷积水碳库、生态服务评价和 ArcGIS Pro 出图。用户提供 project.json、影像、LULC、ROI、碳密度或驱动因子，并需要由本地 ENVI、PyTorch、PLUS、InVEST 或 ArcGIS Pro 完成工作时使用。
---

# 矿区生态空间分析

1. 读取 `project.json`；没有项目文件时从 `templates/local_project.json` 创建。按已启用模块收集输入，不要求与当前任务无关的数据。
2. 调用 `list_backends` 与目标 `backend_capabilities`，再运行 `validate_local_project` 和 `compile_project_workflow`。以编译出的工作流为运行来源。
3. 使用 `run_local_project` 执行本机可用阶段。保留 `agent_state.json`、日志、`outputs_manifest.json`、`provenance.json` 和 `validation_summary.json`。
4. 让 PLUS 每个情景写入 `outputs/plus/<scenario>/PLUS_<scenario>.tif`。本机桥接器未配置时报告 `prepared`；GUI 结果放入该路径后再次运行即可接管。RE 传入米制、`positive_down`、与主网格对齐的 `core_driver_input`。
5. 在分类、PLUS 和 InVEST 前后运行空间预检：CRS、像元、范围、行列数、NoData、LULC 整数编码、碳密度覆盖、沉陷深度非负和高程基准。分类独立验证产生 OA、F1、IoU、分类别指标和混淆矩阵。
6. PLUS 与 InVEST 同时启用时，按 ND、UD、EP、RE 分别计算碳储，并把四个总碳结果送入生态服务评分、权衡、敏感性、情景比较和可选 GeoDetector。
7. 将源数据视为只读。读取路径限于 `security.input_roots`，输出留在 `workspace`；遇到现有输出时请求 `confirm_overwrite`。
8. 如果模型目录提供 `model/model.json` 与 `best_resnet50.pth`，先验证 SHA-256。该模型是 RGB 图块分类器，不是语义分割模型：只聚合到普通六类体系，输出标为 `pending_validation`，未经独立验证和用户显式确认不得接入 PLUS/InVEST 主链。

状态使用 `accepted`、`running`、`completed`、`prepared`、`pending_validation`、`waiting_interactive`、`failed` 或 `cancelled`。`prepared` 和 `pending_validation` 都不表示分析已完成。

按需查阅 `plus_model/`、`invest_carbon/`、`ecosystem_service/`、`arcgis_steps/` 与 `envi_classification/` 的模块说明。
