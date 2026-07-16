# HPSCIL PLUS 官方快照 GUI 自动化桥

本模块固定连接 [HPSCIL/Patch-generating_Land_Use_Simulation_Model](https://github.com/HPSCIL/Patch-generating_Land_Use_Simulation_Model) 的一个可复现本地快照：官方 `origin`、提交 `de7ba6efd35b530da6c37e81103276a17716602c`、仓库内 `PLUS V1.4.2.exe` 文件名及其 SHA-256 都会核验。

版本证据存在冲突，桥接器会如实记录而不自行裁定：该仓库没有 Git tag 或 GitHub Release；README 仍出现 V1.0；实际启动后 Qt 窗口标题为 `Patch-generating Land Use Simulation (PLUS) Model V1.4.1`。因此这里的 “v142” 仅表示配置键、EXE 文件名和桥接器文件名，不表示已经由厂商发布记录证实的软件版本。

桥接器不通过公网控制软件。MCP、提权子进程、PLUS 和全部输入输出均在同一台 Windows 电脑本地运行。

## 安装与配置

```powershell
.\scripts\setup_agent.ps1 -WithPlusGui
```

`config/local_paths.json` 需要指定官方快照位置和指纹：

```json
{
  "plus_v142_repository": "D:\\PLUS\\official_HPSCIL_snapshot",
  "plus_v142_executable": "D:\\PLUS\\official_HPSCIL_snapshot\\PLUS V1.4.2.exe",
  "plus_v142_version": "unverified: executable filename only",
  "plus_v142_commit": "de7ba6efd35b530da6c37e81103276a17716602c",
  "plus_v142_sha256": "2f49f4f01c0a209d0d67fabef9013d41fca30b1632e334898abadad5c2eb25d4",
  "plus_v142_requires_elevation": true,
  "plus_v142_ui_profile": "D:\\MAESA-Agent\\config\\plus_v142_ui_profile.json",
  "plus_bridge_command": ["{python}", "{skill_root}/scripts/plus_v142_gui_bridge.py"]
}
```

该 EXE 在本机要求管理员权限。桥接器会通过本地 UAC 提权子进程运行同一份 Python 脚本，使 pywinauto 可访问同等权限的 Qt 窗口；它不会关闭 UAC、创建网络服务或传出数据。

## 校准与运行

`calibrate_plus_v142(workspace, process_id, open_menu, open_menu_item)` 只采集控件树与截图。第一次运行会产生本地校准报告和截图；必要时可传入正在运行的 PLUS 进程 PID 以附着而非启动第二个窗口。

将可复核的控件选择器写入本地、已忽略的 `config/plus_v142_ui_profile.json` 后才可设 `calibrated: true`。运行时优先用 pywinauto 的控件标题、AutomationId 和控件类型；控件树缺失时才使用同目录的 OpenCV 截图模板。支持 `click`、`set_text`、`select`、`menu`、`hotkey`、`wait` 与 `capture`。

ND、UD、EP、RE 分别拥有请求、状态和输出目录。存活的 GUI 会话可续跑；已退出的窗口会完整重放已校准的输入序列。仅当约定的 `PLUS_<scenario>.tif` 已写入且通过单波段整数 LULC、CRS、行列数和主网格一致性检查时，桥接器才返回 `completed`；其余情况返回 `waiting_interactive`。
