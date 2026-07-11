# ArcGIS Pro 最终图件输出

每个模块的空间结果在 ArcGIS Pro 中完成检查、符号化和布局输出：

- 土地利用分类图与置信度图；
- PLUS 各情景预测图和转移图；
- InVEST 碳储量图与碳变化图；
- 沉陷深度、沉陷积水深度、库容和边界图；
- 生态服务评价等级图。

在项目配置的 `gis_outputs` 中提供 `.aprx` 和布局名称后，可使用 `export_layout` 操作导出 PDF 和 PNG：

```json
{
  "id": "export_final_layout",
  "type": "export_layout",
  "aprx": "project.aprx",
  "layout_name": "Final Layout",
  "pdf": "outputs/maps/final_layout.pdf",
  "png": "outputs/maps/final_layout.png",
  "resolution": 300
}
```

出图前必须核对图层数据源、坐标系、NoData 显示、分类颜色、地类编码、标题年份和情景名称。导出的云图不替代用于 PLUS 或 InVEST 的原始数值栅格。
