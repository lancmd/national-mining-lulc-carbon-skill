# PyTorch 土地利用分类执行规范

## 模型包类型

本项目支持两种模型包；先识别模型输出类型，再决定它能进入哪一条工作流。

### A. 语义分割模型

用于生成逐像元土地利用图。完整目录格式如下：

```text
model_package/
├── model_config.json
├── model.pt2
└── model_card.md
```

优先使用 `torch.export.save` 生成的 `.pt2`；兼容已有 TorchScript `.pt`。不直接加载来源不明的完整 Python pickle。若用户只有一般 `state_dict`，应由模型作者在可信环境中提供网络结构并导出为 `.pt2`。

`model_config.json` 固定传感器、波段顺序、归一化、分辨率、patch、类别编码和模型文件哈希。模板见 `templates/pytorch_model_config.json`。这类模型可作为 PLUS、InVEST 和制图主链的 LULC 输入。

### B. 已登记的 ResNet-50 图块分类器

用户本地 `model/model.json + model/best_resnet50.pth` 形式的包可直接登记。当前已适配的 ResNet-50 输出为每个 RGB 图块一个类别，而不是每个像元一个类别：

- 模型输出 8 类：其他用地、耕地、林地、草地与其他绿地、城乡住宅与商业用地、工业用地、交通运输用地、水域与水利设施用地；
- 在普通六类体系中，住宅/工业/交通合并为建设用地，其他用地临时映射为裸地/工矿用地；
- 它不能识别“沉陷积水”和“自然水体”的差异，不能直接用于高潜水位七类体系；
- 推理结果是粗分辨率图块网格，报告中会明确标为 `coarse_patch_grid_not_pixelwise_segmentation`；它在独立精度评价通过前保持 `pending_validation`。

已登记的元数据和类别聚合见 [`registered_models/lulc_resnet50_8class.json`](registered_models/lulc_resnet50_8class.json)。权重保留在用户本地模型目录，不提交到 Git。

该适配器只接受已验证 SHA-256 的 `pytorch_state_dict`，并只构建已登记的 `resnet50` 结构；不加载任意 Python pickle。运行时要求 `torch`、`torchvision`、`numpy` 和 `rasterio`。

```powershell
python scripts/pytorch_patch_lulc.py audit `
  --model-package <本地ResNet50模型目录>

python scripts/pytorch_patch_lulc.py infer `
  --model-package <本地ResNet50模型目录> `
  --input-raster <多波段影像.tif> `
  --class-output <标准六类图块网格.tif> `
  --confidence-output <置信度.tif> `
  --patch-size 256 --stride 256 `
  --band-indexes 1,2,3 --input-scale 1.0
```

`patch_size`、`stride`、RGB 波段和输入比例因子是模型契约的一部分。图块大小的米制范围由输入影像分辨率决定；没有训练图块物理范围和独立验证样本时，不应把结果接入 PLUS 或 InVEST 主链。只有人工确认 `patch_classifier.allow_as_lulc=true` 并完成独立精度评价后，项目编译器才允许其进入完整链路。

通过 MCP 的 `build_local_project_from_inputs` 创建项目时，传入 `patch_size`、`patch_stride`、`patch_band_indexes` 和 `patch_input_scale`；适配器会自动识别该包，并将分类体系设为普通六类。`full_chain` 仍会等待独立验证与显式确认。

## 类别策略

推荐模型输出高潜水位七类全集。普通矿区在推理后将沉陷积水与自然水体合并，而不是临时改变模型输出通道。新增模型未训练过的类别时必须重新训练或微调。

## 语义分割推理

1. 确认输入影像的传感器、波段、比例因子和分辨率与模型配置一致。
2. 运行 `validate-model`；文件哈希、类别和预处理不完整时停止。
3. 按 patch 分块推理，以重叠权重融合接缝。
4. 输出分类 GeoTIFF、最大概率置信度 GeoTIFF 和运行报告。
5. 低置信度像元保留原类别，但加入复核掩膜；不得无依据地改成背景。

```powershell
python scripts/pytorch_lulc.py validate-model --model-package <模型目录>
python scripts/pytorch_lulc.py infer --model-package <模型目录> `
  --input-raster <多波段影像.tif> --class-output <分类.tif> `
  --confidence-output <置信度.tif> --device auto
```

## 科研验收

- 报告模型版本、训练区域、训练年份和传感器；
- 输入波段顺序与模型配置完全一致；
- 使用独立验证样本输出混淆矩阵、总体精度、F1/IoU 和分地类精度；
- 跨矿区直接迁移时把精度状态标记为 `pending_validation`；
- 输出类别编码与 `config/landuse_classes.md` 一致；
- 沉陷积水在基础推理后再结合工作面、沉陷范围、历史新增水体和低洼地形筛选。
