# PLUS GUI 运行状态与接管

官方 PLUS V1.4.2 快照通过本地 GUI 桥接器运行。桥接器不会把窗口已打开、按钮已点击或输出文件刚出现误报为预测完成。

每个情景写入独立目录 `outputs/plus/<scenario>/`，并保存请求包、状态文件、窗口截图（如有）、UI profile 哈希、官方仓库提交、EXE 哈希、输入清单、时间戳及输出栅格验证报告。

状态文件中的 `lifecycle_status` 依次使用：

`prepared` → `calibration_required` / `waiting_uac` → `running_gui` → `waiting_export` → `output_detected` → `validated` → `completed`

协议层仍使用 MAESA 通用状态：`prepared`、`waiting_interactive`、`running`、`completed` 或 `failed`。例如在 `waiting_uac` 与 `waiting_export` 时，协议响应为 `waiting_interactive`，工作流暂停而不是失败；再次运行同一项目会读取本情景的状态文件并继续接管。

`completed` 仅在下列检查通过后返回：输出为单波段整数 GeoTIFF、具有 CRS、尺寸有效，并与最后一期历史 LULC 的 CRS、范围、行列数和仿射变换一致。真实四情景项目应保留为本机回归数据，不进入公共 CI。
