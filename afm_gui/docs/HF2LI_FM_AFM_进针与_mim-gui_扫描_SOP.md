# HF2LI FM-AFM 进针与 mim-gui 扫描 SOP

版本：2026-09-29  
适用程序：`GUI-for-mim` 当前 `FM-AFM / HF2 AUX XY` 配置

## 1. 适用范围与安全边界

本文分为两部分：先在 LabOne 中完成自由共振、PLL/PID 设置和受控进针，再在闭环稳定后使用 mim-gui 控制 AUX1/2 扫描成像。

与旧 SOP 相比，AUX3 和 AUX4 的用途已经对调。当前接线是：

| HF2 端口 | 当前用途 | mim-gui 是否写入 |
| --- | --- | --- |
| AUX1 | X 扫描电压 | 是，仅写 Offset |
| AUX2 | Y 扫描电压 | 是，仅写 Offset |
| AUX3 | Z PID 输出 | 否，只读取和检查 |
| AUX4 | PLL1 频率偏移 Δf 的电压输出 | 否，只读取和检查 |
| Aux In 1 | 接收 AUX4 回环，作为 Z PID 输入 | 否 |

当前程序不配置 PLL、PID、激励、AUX3 或 AUX4；这些项目必须先在 LabOne 中设置并验证。

> **重要安全限制：** 当前 mim-gui 检测到 PLL 失锁、PLL/PID 关闭、AUX3 越界或必要信号读取失败时，会停止 XY 并取消后续扫描序列，但**不会自动关闭 PID，也不会自动撤针**。Stop 也不是硬实时急停；若 LabOne API 正在阻塞，需要等当前通信返回。若实验必须满足“失锁后自动关闭 PID”，当前版本在完成相应代码和实机验证前不满足该要求。

当前室温软件限值为 AUX1、AUX2、AUX3 均 `0...5 V`。软件限值不能代替扫描台、放大器和低温条件下的实际标定。

---

# 第一部分：PLL/PID 设置与进针

## 2. 当前信号链

```text
HF2 Signal Output 1 ──> 激励压电片 ──> 音叉
音叉/前置放大器 ──> HF2 Signal Input 1 ──> PLL 1
                                                    │ Δf
                                                    v
HF2 AUX4 ───────────────────────────────────> HF2 Aux In 1
Signal = PLL1 frequency shift                         │
Scale = a, Offset = V0                                v
                                                   PID 1
                                                    │ Aux Output Offset / channel 3
                                                    v
HF2 AUX3 ──> Archimedes Analog In 3 ──> Z 高压 ──> Z 扫描台

HF2 AUX1 ──> Archimedes X 模拟输入 ──> X 扫描台
HF2 AUX2 ──> Archimedes Y 模拟输入 ──> Y 扫描台
```

关系式为：

```text
V4 = a × Δf + V0
PID Input = Aux In 1 ≈ V4
PID Output = AUX3 Offset
```

## 3. 接线与上电检查

所有接线应在针尖远离样品、PID 关闭、输出处于已知安全状态时完成。

1. `Signal Output 1` 接音叉激励压电片。
2. 音叉检测信号经合适前置放大器后接 `Signal Input 1`。
3. AUX1、AUX2、AUX3 分别接扫描控制器 X、Y、Z 模拟输入；当前 Z 约定为 `Analog In 3`。
4. AUX4 用 BNC 回接 HF2 背板 `Aux In 1`。
5. Archimedes 的 XYZ 高压输出分别接指定扫描台轴，不得接回 HF2。
6. 对应轴进入外部模拟输入模式；当前系统使用 OLAI。
7. attocube 只承担粗进针，不接到 HF2 AUX 输出。

此时保持 `PLL 1 = OFF`、`PID 1 = OFF`、XY 不扫描，并在 LabOne 确认：

- AUX1：`Signal = Manual`；
- AUX2：`Signal = Manual`；
- AUX3：`Signal = Manual`、`Scale = 0`；
- 没有其他已启用 PID 占用 AUX1/2。

将 AUX3 Offset 设为已验证的安全值，用万用表核对 AUX3、Archimedes 输入及高压倍率。用极小阶跃确认 AUX1/2/3 的机械方向，然后恢复原值。建立现场记录，写清各轴模拟输入、增益、电压增大时的运动方向和安全回撤方向。

若外部输入增益约为 `×15`，则 `0...5 V` 对应约 `0...75 V` 高压；最终以当前控制器设置和实测为准。

## 4. 测量自由共振

温度、音叉、接线、安装力、前放或滤波设置变化后，都应重新扫频。

1. 针尖远离样品，PID 和 PLL 均关闭。
2. 在 LabOne Sweeper 中选择实际驱动振荡器和检测解调器。
3. 先宽扫找到唯一共振峰，再缩小范围慢速细扫。
4. 从同一次细扫记录 `f_free`、峰值相位 `phi_res`、自由振幅 `R_free` 和 Q。
5. 重复细扫；结果不能重复时，先排查机械振动、接地、前放饱和和扫速。

PLL 相位设定应使用完整测量链路实测的 `phi_res`，不能直接套理论相位。

## 5. 设置并验证 PLL 1

1. PLL 输入选择实际检测音叉的解调器。
2. `Center Frequency = f_free`，`Phase Setpoint = phi_res`。
3. 初次使用保守的 Range 和带宽；Range 应明显大于目标带宽，且只覆盖当前共振峰的单调相位段。
4. 使用 PLL Advisor 计算内环参数，不照搬其他探针或温度的参数。
5. 打开 PLL，等待稳定，同时检查 Lock、相位误差、Δf、振幅和实际振荡器频率。
6. 若自由状态下 Δf 长时间偏离零，确认共振漂移后修正 Center Frequency，不能用外层 PID 掩盖基准错误。

PLL 绿灯只代表相位误差符合判据，不代表一定锁在正确共振峰；必须结合扫频曲线、振幅和实际频率判断。

## 6. 标定 AUX4 → Aux In 1 的 Δf 回环

保持 PLL 已锁定、PID 关闭。

1. AUX4 设置为 `Signal = PLL 1 Frequency Shift`、`Scale = a`、`Offset = V0`。
2. 确认 AUX4 已回接 Aux In 1。
3. 同时读取 PLL Δf、AUX4 和 Aux In 1，并用万用表核对：

```text
AUX4 实测值 ≈ Aux In 1 ≈ a × Δf + V0
```

4. 至少检查零点和一个非零点，确认比例、正负号及预期范围内不饱和。
5. 记录 `a`、`V0` 以及 `AUX4 − Aux In 1` 的典型误差。

若比例或符号不符，先检查接线、Scale 和 Offset，不能靠反转 PID 符号补偿错误标定。

## 7. 确认 Z 方向和反馈符号

针尖远离样品、PID 关闭时，从当前安全值给 AUX3 一个极小阶跃，例如 `5...10 mV` 或更小，并立即恢复，记录：

```text
AUX3 增大：靠近 / 远离
AUX3 减小：靠近 / 远离
```

进入相互作用区后仍保持 PID 关闭：

1. 记录 `V3_old`、`V4_old` 和 Δf。
2. 给 AUX3 一个已验证安全的极小阶跃 `ΔV3`。
3. 等 PLL 稳定，记录 AUX4 的变化 `δV4`，随后恢复 AUX3。
4. 计算静态对象增益符号：

```text
G = δV4 / δV3 = a × δ(Δf) / δV3
```

若 PID 误差定义为 `Error = Setpoint − Input`，P、I 符号应与实测 `G` 同号。必须用小阶跃验证，不能只依赖公式或旧参数。

## 8. 用 attocube 粗进针

粗进针状态必须为：

```text
PLL：ON 且稳定锁定
PID：OFF
XY 扫描：OFF
AUX3/Z：处于安全位置并保留双向余量
```

1. 远离样品时可用较大粗步；视觉接近后切换到最小可靠步进。
2. 每步后停止并等待机械振动与 PLL 稳定。
3. 每步观察 Δf、振幅、相位误差和 PLL Lock。
4. 自由状态先记录 10...30 s 的 Δf 噪声，估计 `σf`。
5. 第一次出现方向一致、可重复且明显高于噪声的变化时停止；`5σf` 只能作为保守识别参考，不是工作点。
6. 视机械裕量粗退一小步，将剩余接近交给 Z 扫描台和 PID。

Δf 大跳、振幅塌陷、PLL 失锁、持续相位误差、Z 接近限位或异常机械移动时，立即停止前进并回撤。

## 9. 设置 Δf 工作点和 PID 1

在响应仍单调、信号明显高于噪声、又远离突变和振幅塌陷的位置选择 `df_set`：

```text
Vset = a × df_set + V0
```

保持 PID 关闭，在 LabOne 设置：

- `Input = Auxiliary Input`，通道为 `Aux In 1`；
- `Setpoint Mode = Manual`；
- `Output = Auxiliary Output Offset`，通道为 `Aux Out 3`；
- AUX3 保持 `Signal = Manual`、`Scale = 0`。

不要把 AUX3 Signal 再设为 PID 输出并使用非零 Scale，否则可能形成重复叠加路径。

### 9.1 Center、Range 和停环输出

1. 读取当前安全 AUX3 电压 `V3_now`，令 PID `Center = V3_now`。
2. `Default Out` 设为已验证的安全值，并实测 PID 关闭时的输出与机械方向。
3. 初次只给很小 Range，例如中心附近几十毫伏或更小。
4. 室温 `0...5 V` 条件下必须满足：

```text
0 V <= Center − Range
Center + Range <= 5 V
Range <= min(Center, 5 V − Center)
```

`Center=0 V, Range=5 V` 会允许负输出，是错误设置。数学上开放整个 `0...5 V` 需 `Center=2.5 V, Range=2.5 V`，但第一次调试不得直接开放整个行程。

### 9.2 初始增益与无跳变启环

先令 `P` 很小且符号已验证，`I=0`、`D=0`；外层 Z PID 必须明显慢于 PLL。

1. 停止粗位移与 XY，确认 PLL 稳定。
2. 确认 AUX3、Center、Range 和停环输出都安全。
3. 先令 PID Setpoint 等于当前 Aux In 1，使启环误差接近零。
4. 打开 PID，观察 AUX3、AUX4/Δf、PID Error、PLL Lock 和振幅。
5. 将 Setpoint 分成小台阶缓慢移向 `Vset`，每步稳定后再继续。
6. 到达目标后确认 Error 接近零、PLL 持续锁定、振幅正常、AUX3 未顶限。

若误差增大、输出冲向限位或方向错误，立即按已验证的停环与回撤步骤处理。

## 10. 调 P/I 与稳定判据

1. `I=0、D=0`，用很小 Setpoint 阶跃调整 `|P|`。
2. 响应太弱时逐步增加；出现过冲、振荡或噪声放大时退回稳定值。
3. 从很小的 `|I|` 开始加入积分；出现慢振荡、长过冲或限位积分时减小。
4. D 暂时保持零，除非已完成传递函数、延迟和噪声评估。

稳定后至少观察 30 s，并确认 PLL 持续锁定、振幅正常、AUX4 与 Aux In 1 一致、PID Error 小、PID 未顶限、AUX3 离 0/5 V 有余量且不持续单向爬升。

## 11. 异常处理与正常退出

异常时：

1. 立即停止 attocube 和 XY；若 mim-gui 正在扫描，点击 `Stop`。
2. 按实机验证过的顺序在 LabOne 关闭 PID。关闭前必须知道停环输出把 Z 带向何处。
3. 沿已记录的安全方向缓慢改变 AUX3，使 Z 回撤。
4. 信号恢复后，再让 attocube 粗退若干步。
5. 保存监测历史、扫描报告和 Command Log，检查 PLL、前放、路由、P/I 符号和限位。

正常退出顺序：停止 XY；把 Setpoint 分步移回弱相互作用；确认停环输出安全后关闭 PID；用 AUX3 回撤 Z；attocube 粗退；最后关闭 PLL 和激励。

不要在疑似接触时直接切断 Archimedes 电源；断电后的位移方向可能加重接触。

---

# 第二部分：mim-gui 扫描

## 12. 启动与连接

在含 `pyproject.toml` 的 `GUI-for-mim` 目录打开 PowerShell：

```powershell
conda activate mim-gui
python -m afm_gui.main
```

当前项目默认 HF2 参数为：

```text
host: 127.0.0.1
port: 8005
device: DEV18388
interface: USB
```

参数必须与远程电脑实际设备一致。不要因连接失败就盲目改端口，可先运行：

```powershell
Test-NetConnection 127.0.0.1 -Port 8005
```

端口连通不代表版本兼容；若提示 version mismatch，应让 Python 的 `zhinst-core` LabOne 主次版本与 Data Server 对应。

在 `Device Manager` 中确认 `Scan Scanner` 和 `Lock-in Detection` 都分配给 `zurich_HF2LI`，然后选择它点击 `Connect`，或点击 `Connect Enabled`，等待状态显示 `Connected`。

## 13. 扫描前 LabOne 条件

点击扫描后程序会预检，以下条件缺一不可：

1. AUX1、AUX2 为 Manual，且无启用的 PID 占用它们。
2. AUX3 为 Manual、`Scale=0`。
3. PID 1 路由为 `Aux In 1 → Aux Out 3 Offset`。
4. AUX4 信号源为 `PLL1 Frequency Shift`。
5. PLL 1 已启用并锁定，PID 1 已启用并稳定。
6. PID `Center ± Range` 和 AUX3 实际值均在 `0...5 V`。
7. 旋转后的整个 XY 扫描区域都在 AUX1/2 的 `0...5 V`。

程序不会替你修正配置，只会拒绝扫描并在 Command Log 记录原因。

## 14. 用 FM-AFM Monitor 预检

点击 `Read Once` 或 `Start Monitor`，检查：

- `PLL locked=1`、`PLL enabled=1`、`Z PID enabled=1`；
- AUX3 位于安全范围并有余量；
- AUX4 与 Δf 变化一致；
- `Aux In 1 − Aux Out 4` 接近回环误差；
- PID Error 小，`PID at limit=0`。

默认时间曲线为 AUX3、AUX4、PID Error；需要留存时使用 `Export History CSV`。

Monitor 可以与扫描并行，但与扫描共享 HF2 通信锁，可能降低扫描速度。高速扫描前建议先用 Read Once 验证，再停止 Monitor；必须持续监测时使用较慢刷新间隔并实测总时间。

## 15. 手动移动 XY

Manual XY 的单位是 HF2 AUX1/2 低压端 V，不是放大后的高压，也不是 nm。

1. 先启动 Monitor 读取当前 AUX1/2。
2. 点击 `Copy Live XY`。
3. 输入经过验证的目标 X、Y 和 Speed，再点击 `Move XY`。
4. 程序按当前 `max_step_v=0.01 V` 分步限速移动。
5. `Stop XY / Hold` 只停止移动并保持当前电压，不归零。

不要直接保留默认 `2.5 V` 就移动，除非已确认当前硬件位置和完整路径安全。

## 16. 设置扫描参数

选择 `FM-AFM / HF2 AUX XY`，设置：

- `Center X/Y`：AUX1/2 扫描中心，单位 V；
- `Width/Height`：扫描范围，单位 V；
- `Angle`：图像旋转角；
- `Pixels/Lines`：每行像素和总行数；
- `Linear`：XY 电压变化速度，单位 V/s；
- `Sample`：每点移动后的等待时间；
- `Settle`：每个 trace/retrace 起点的等待时间；
- `Rest`：一整行 trace+retrace 完成后的等待时间。

旋转扫描时四个旋转端点都必须在 `0...5 V`，程序会在开始前检查。

### 16.1 当前版本固定采集 trace 和 retrace

当前 FM-AFM 模式没有关闭 retrace 的界面选项。每行实际执行：

```text
trace：X 从行起点扫到终点，采集 Pixels 个点
retrace：X 从终点扫回起点，再采集 Pixels 个点
Y：trace 和 retrace 全部完成后才步进到下一行
```

所以 `Pixels=32` 时每行物理上采集 `32 trace + 32 retrace = 64` 个样本，但分别保存为两张 32 列图，不会拼成一张 64 列图。

估时近似为：

```text
Lines × [2 × (Width / Linear + Settle + Pixels × Sample) + Rest]
```

实际时间还包含每点 LabOne 写入/读取、路由检查、行起点定位、Python/Qt 调度和可选 Monitor 读取，因此界面估计不是硬件定时保证。

## 17. 记录通道和图像显示

当前默认记录：

- `Aux Out 3 / Z PID output`：Z 反馈电压，V；
- `Aux Out 4 / PLL Δf output`：Δf 电压映射，V；
- `PLL frequency shift`：Δf，Hz；
- `Z PID error`：PID 误差，V；
- `Tracked frequency`：PLL 跟踪频率，Hz。

可按需要增加 R、PLL phase error、Aux In 1 等通道；勾选会立即同步到 Channel Images 下拉框。

AUX3 是 Z 控制电压，不是已经标定的样品高度。没有 Z 标定时，不得把它解释为 nm。

Channel Images 可分别选择通道、trace/retrace、Raw/Line Mean/Plane、色图及 Auto/Manual color range。Auto range 会随有效采样值更新；显示 flatten 不修改保存的原始数据。

## 18. 设置保存目录

Controls 中的 Auto Save directory 默认为：

```text
%USERPROFILE%\AFM_scans
```

- 勾选 `Auto Save`：暂停和结束时自动保存每个通道/pass 的 `.gsf` 及 `_metadata.json`。
- 不勾选 Auto Save：不自动导出 GSF，但每次完成、手动停止或异常中止仍会写 `*_scan_report.txt`。
- scan report 记录扫描参数、通道、显示设置、状态、错误以及最终 HF2 PLL/PID/AUX 快照。
- `Save GSF` 可手动另存当前数据。

扫描前确认目录可写、磁盘空间足够。

## 19. 开始单次扫描

新的探针、样品、温度或 PID 参数第一次扫描时，只使用 `Single`：

1. 确认闭环稳定且 PID 未顶限。
2. Repeat 选择 `Single`。
3. 点击 `Scan Up` 或 `Scan Down`。它只改变 Y 行顺序；每行仍先 trace 后 retrace。
4. 观察 Command Log，确认预检成功、扫描启动和记录通道正确。
5. 观察 State 中的 pass、line、pixel 和 Channel Images 逐行更新。
6. 同时在 LabOne 或低频 Monitor 中关注 PLL Lock、AUX3 和 PID Error。

扫描开始后，几何、通道和手动 XY 被禁用；Linear、Sample、Settle、Rest 的修改从下一行生效。

## 20. 暂停、继续、停止和重复扫描

- `Pause`：在安全检查点暂停；AUX1/2 保持当前值，PID 继续由 LabOne 运行。Auto Save 开启时会保存 pause 数据。
- `Resume`：从暂停处继续。
- `Stop`：请求停止 XY，AUX1/2 保持当前位置；不归零、不撤针、不关闭 PID。

Stop 需等待当前 LabOne API 调用返回，不能代替硬件急停。

只有单次扫描成功后才能使用：

- `Continuous Up/Down`：Up/Down 连续交替；
- `Count`：按设定次数交替扫描。

安全错误或人工 Stop 都会取消剩余序列。

## 21. 扫描中的自动检查和人工处置

程序逐点检查：

- PLL 是否启用并锁定；
- PID 是否启用；
- AUX3 是否处于 `0...5 V`；
- 所有选中通道是否读取成功。

程序还周期性复查 AUX1/2 路由。任一检查失败时，XY 停止、连续序列取消、报告记录错误，但 PID 继续由 LabOne 控制。

异常后应：

1. 确认 XY 已停止，必要时点击 Stop。
2. 查看 Command Log 和 State 错误。
3. 在 LabOne 检查 PLL、PID、AUX3 和机械状态。
4. 按第一部分已验证的顺序停环和回撤。
5. 保存 Monitor CSV、scan report、GSF/metadata 和 Command Log。
6. 排除失锁、越界、饱和或通信问题后，从小范围 Single 重新验证。

## 22. 扫描完成后的检查

1. State 回到 Idle，Command Log 显示 `Scan finished`。
2. trace/retrace 图像均存在；比较漂移、滞后和反馈差异。
3. AUX3 未靠近 0/5 V，PID Error 无持续偏置。
4. 输出目录中存在预期 GSF、metadata 和 scan report。
5. scan report 的状态应为 `COMPLETED`；若为 `FAILED` 或 `STOPPED`，查看 error/stop reason。
6. 备份同一扫描的完整文件组，不要只复制单张 GSF。

## 23. 每次进针前快速检查表

```text
[ ] 当前接线是 AUX1=X、AUX2=Y、AUX3=Z PID、AUX4=PLL Δf
[ ] AUX4 已回接 Aux In 1
[ ] f_free、phi_res、R_free、Q 来自本次自由扫频
[ ] PLL 锁在正确共振峰，不只是绿灯亮
[ ] AUX4 的 a、V0、符号和 Aux In 1 回环已实测
[ ] AUX3 增大/减小对应的 Z 方向已记录
[ ] G=δV4/δV3 和 P/I 符号已用小阶跃验证
[ ] PID Input=Aux In 1
[ ] PID Output=Aux Out 3 Offset
[ ] AUX3 Signal=Manual、Scale=0
[ ] PID Center±Range 全部在 0...5 V
[ ] PID 关闭时的输出和回撤方向已验证
[ ] 粗进针时 PLL ON、PID OFF、XY OFF
[ ] 开 PID 前 Setpoint 先等于当前 Aux In 1
[ ] 最终 Setpoint 分小步逼近
[ ] 已知道人工停环和回撤顺序
```

## 24. 每次扫描前快速检查表

```text
[ ] Data Server 端口和 zhinst 客户端版本匹配
[ ] HF2LI 已连接并分配给 Scan Scanner/Lock-in
[ ] PLL enabled=1、locked=1
[ ] PID enabled=1、error 小、未顶限
[ ] AUX1/2 为 Manual，XY 路径安全
[ ] AUX3 当前值和 Center±Range 均在 0...5 V
[ ] AUX4=PLL1 frequency shift，Aux In 1 回环正常
[ ] 旋转后的扫描四角均在 XY 0...5 V
[ ] 已理解每行固定采集 trace+retrace
[ ] 记录通道和 Channel Images 选择正确
[ ] 保存目录可写、磁盘空间足够
[ ] 第一次使用 Single、小范围、少像素/少行
[ ] 已打开 LabOne 或低频 Monitor 观察安全量
```

## 25. 实验记录表

| 项目 | 数值 | 备注 |
| --- | ---: | --- |
| 日期/操作者 |  |  |
| 温度、样品、探针 |  |  |
| `f_free` / `phi_res` |  | Hz / deg |
| `R_free` / Q |  |  |
| PLL Range / target BW |  | Hz |
| Δf 噪声 `σf` |  | Hz，记录时长 |
| AUX4 Scale `a` / Offset `V0` |  | V/Hz / V |
| AUX3 增大时 Z 方向 |  | 靠近/远离 |
| `G=δV4/δV3` 符号 |  | 正/负 |
| `df_set` / `Vset` |  | Hz / V |
| PID Center / Range |  | V / V |
| P / I / D |  |  |
| XY 中心/宽高/角度 |  | V / V / deg |
| Pixels × Lines |  |  |
| Linear / Sample / Settle / Rest |  |  |
| 记录通道 |  |  |
| 数据目录 |  |  |
| 紧急回撤方向 |  | AUX3 增大/减小 |

## 26. 参考依据

- 当前配置：`afm_gui/config/devices.yaml`、`afm_gui/config/scan_modes.yaml`；
- 当前行为：`afm_gui/device/adapters/hf2_fm.py`、`afm_gui/device/scan_device.py`；
- Zurich Instruments HF2 用户手册与 Node Documentation；
- 多场科技扫描台、MC-ArchimedesLT.03 和 attocube 控制器手册。

硬件手册、实验室安全规程和现场实测优先于本文示例数值。
