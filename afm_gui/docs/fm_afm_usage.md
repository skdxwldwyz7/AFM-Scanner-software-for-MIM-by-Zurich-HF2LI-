# FM-AFM：HF2LI 读取、AUX XY 扫描与时间曲线

正式进针或使用 GUI 扫描前，请先阅读并执行
[HF2LI FM-AFM 进针与 mim-gui 扫描 SOP](HF2LI_FM_AFM_进针与_mim-gui_扫描_SOP.md)。
该 SOP 以当前 AUX1=X、AUX2=Y、AUX3=Z PID、AUX4=PLL Δf 接线为准。

## 当前控制分工

默认配置只连接 Zurich HF2LI。多场 scanner 控制器在 **OLAI** 模式下接收外部模拟电压，GUI 不连接它的串口。原有 `ui → core → device → data` 分层、扫描几何、正反扫、图像和 GSF 导出框架保留。

| HF2 端口 | 接线/用途 | 本程序操作 |
|---|---|---|
| AUX1 | 控制器 X 模拟输入 | 读取输出值；按扫描或手动目标写 Offset |
| AUX2 | 控制器 Y 模拟输入 | 读取输出值；按扫描或手动目标写 Offset |
| AUX3 | Z PID 输出，接控制器 Analog Input 3 | 只读；不直接设置 Z |
| AUX4 | PLL1 Δf 转电压，接 HF2 Aux In 1 | 只读输出值 |
| Aux In 1 | 接收 AUX4 的 Δf 电压 | 程序不读取；由 LabOne PID 使用 |

控制器侧 X/Y/Z 的实际输入端口和增益需按你的控制器接线核对。GUI 的 V 始终指 **HF2 辅助输出低压端**，不是控制器放大后的高压，也不是 nm。AUX3 可作为 Z 反馈电压成像，但未经 scanner 标定不能当作真实高度。

## LabOne 侧先完成的设置

遵循你的 `HF2LI_PLL_PID_Z进针_SOP.md`，本程序不会替你修改这些设置：

1. AUX1、AUX2 的 Signal 设为 **Manual**，确认没有启用的 PID 控制这两个输出。程序只写 Offset，不切换 Signal。
2. AUX4 使用 **PLL1 frequency shift**，设置合适的 Scale/Offset 并接回 Aux In 1。
3. Z PID 输入为 **Auxiliary Input / channel 1**，输出为 **Auxiliary Output manual（Offset）/ channel 3**。
4. AUX3 为 **Manual、Scale=0**；按你的实验条件设好 PID center、range、设定值和反馈方向。
5. 正式扫描前，PLL 启用且锁定，Z PID 启用。激励、解调器和反馈参数继续由 LabOne 管理。

界面端口从 1 开始；API 节点从 0 开始。当前精简模式不读取任何 PLL/PID 节点，也不检查 AUX3/AUX4 路由；这些设置必须在 LabOne 和外部硬件侧确认。

## 安装与启动

从本仓库目录（包含 `pyproject.toml` 的 `GUI` 子目录）运行，需要 Python 3.12 或更新版本以及运行中的 HF2 LabOne Data Server。

```powershell
py -3.12 -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install -e ".[hf2]"
.\.venv312\Scripts\python.exe -m afm_gui.main
```

本机已经建立 `.venv312` 并安装依赖，可以直接执行最后一行启动。离线验证使用 Python 3.12、PyQt6 6.8.1 / Qt 6.8.2；本机另一个 `.venv` 的 Qt DLL 导入失败，不用于本次验证。

在 **Device Manager** 中选择 `zurich_HF2LI`，检查连接参数后点击 Connect Selected；面板可从 View 菜单打开。默认仍沿用项目已有的 `127.0.0.1:8005 / DEV18388 / USB`，序列号和服务器地址需对应实际仪器。`Scan Scanner` 和 `Lock-in Detection` 都应指向同一台 HF2LI。`Connect Enabled` 默认也只连接 HF2LI。

连接、读取和打开 GUI 不会自动移动 XY。FM-AFM 模式下没有未连接时的模拟数据兜底；未连接会阻止扫描。

## 读数和时间曲线

**FM-AFM Monitor** 提供 Start Monitor、Stop Monitor、Read Once。默认目标间隔 500 ms，可设为 100–10000 ms。读取在后台线程完成，可与扫描并行。

Monitor 只批量读取 AUX1、AUX2、AUX3、AUX4 四个输出值，不读取 PLL、PID、解调器或 Aux In 节点。四个时间图默认分别显示 AUX1–AUX4；读数失败显示 N/A，曲线断开，不填假零。

内存保留最近 3600 组快照。Export History CSV 导出当前保留的数据，含 UTC 时间戳、elapsed_s、信号名及单位；Clear History 清空历史。**不是无限时长的后台文件记录。**

这些是软件顺序轮询得到的快照，并非 LabOne 高速订阅流，也不保证不同节点硬件同时采样。真实刷新周期取决于 API 延迟；需要高速同步采样时应进一步增加订阅/缓冲采集模块。

## 手动 XY 与扫描

Manual XY 中输入 AUX1/X 和 AUX2/Y 目标电压、Speed，再点击 Move XY。移动从当前输出读回值开始，分小步斜坡进行；Stop XY / Hold 停在当前值。Copy Live XY 将正在监测的最新输出值复制到输入框，不发送运动命令。

扫描选择 **FM-AFM / HF2 AUX XY**，使用现有 Center、Width、Height、Angle、Pixels、Lines 和正反扫控制。所有 XY 几何量用 V，Linear 用 V/s。初始中心 2.5 V、宽高 0.1 V、速度 0.05 V/s 只是可编辑的起始输入，启动 GUI 不会据此输出电压。

默认且仅可记录 AUX1、AUX2、AUX3、AUX4。Channels 勾选状态会立即同步到 Channel Images 的选择器，默认四幅图分别显示四个 AUX 输出。

采样过程为：移动 → 行起点等待 Settle → 每点等待 Sample → 用一次 `auxouts/*/value` 请求读取 AUX1–AUX4。AUX1/2 更新合并为一次 DAQ 批量命令；客户端未返回完整 wildcard 数据时才退回逐 AUX 节点读取。LabOne API/硬件并不承诺四路是严格同步的硬件采样。实际用时仍包含通信、读取、起始定位和换行开销，界面估算不是精确定时承诺。

扫描中禁用手动 XY 和几何/通道修改；Linear、Sample、Settle、Rest 仍按现有机制在下一行应用。暂停/停止保持输出；没有自动归零或撤针。**Z PID 继续由 LabOne/仪器运行。**

## 限幅、失败和保存

`afm_gui/config/devices.yaml` 中 HF2 的 `connection.fm_afm`：

```yaml
enabled: true
xy_min_v: 0.0
xy_max_v: 5.0
max_step_v: 0.01
```

XY 的 0…5 V 是待按实际 scanner 确认的软件运动范围，不能替代仪器标定或证明运动安全。扫描预检只检查本地几何、时间参数和 XY 范围。程序不再检查 AUX1/2 路由、PID 占用、PLL 锁定、PID 状态/饱和或 AUX3/Z 电压阈值。只有 AUX 读数失败、通信错误或本地参数非法仍会终止扫描。正式实验必须依赖 LabOne 设置和外部硬件保护；通信未返回时 Stop 仍需等待当前 API 调用结束。

GSF 按每个信号/trace/retrace 分文件保存，单位保留为 V/Hz/deg 等。未采到的像素保留 NaN，不伪装成零高度。原有自动保存和参数树继续使用，`runtime.error` 记录扫描错误，FM 监测元数据注明电压含义。配置中的设备信息和最近一次监测值属于软件快照，不能视为 LabOne 全部配置备份。

## 代码入口与验证

| 文件 | 职责 |
|---|---|
| `device/adapters/hf2_fm.py` | AUX1–AUX4 批量读取、XY 本地范围检查；唯一写节点为 AUX1/2 Offset |
| `device/adapters/zurich.py` | 现有 HF2 适配器，增加 FM 接口与串行 I/O 锁；FM 配置阻止旧激励/解调写入 |
| `core/fm_afm.py` | 四个 AUX 通道定义和缺失读数检查 |
| `core/xy_motion.py` | 可中断的 XY 限速斜坡 |
| `device/scan_device.py` | 原扫描后台线程接入 HF2 XY 与采集 |
| `ui/modules/fm_afm.py` / `ui/panels/fm_afm.py` | 监测、手动 XY、读数表、时间曲线、CSV |
| `config/scan_modes.yaml` / `config/layout_fm_afm.json` | FM 默认通道与布局 |
| `tests/test_fm_afm.py` | 模拟 HF2 的节点白名单、预检、线程、导出测试 |

节点依据 Zurich 官方 HF2 文档：<https://docs.zhinst.com/hf2_user_manual/nodedoc.html>。运行 `python -m unittest discover -s tests` 进行离线回归；测试不会连接真实仪器。本次尚未在实际 HF2LI、scanner 和探针上完成联调。
