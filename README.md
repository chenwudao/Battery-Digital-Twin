# 48 V / 13S 锂电池组数字孪生

课程项目：面向电动滑板车 / 小型储能电池组的数字孪生。运维人员只能看到电压、电流、表面温度，
孪生实时估计 **SoC、内阻/健康度、核心温度、剩余续航**，在故障初期给出原因和建议，并支持
what-if 负载评估。

项目自带一个“真实世界”模拟器。Plant 模拟器与 Twin 使用 **不同的模型结构、不同的参数**，
truth 只写入本地 CSV，不经过 MQTT；这避免“用同一个模型验证自己”的循环论证。

## 1. 快速开始

当前目录已经包含本地 `.venv`。直接运行：

```bash
cd battery_dt
source .venv/bin/activate
python scripts/run_all.py --fresh
```

环境：Python 3.12；已在项目内 `.venv` 和一个完全干净的临时 venv 中验证。

打开 <http://localhost:8501>。按 `Ctrl+C` 停止全部服务。

**成品课程视频：** `video/final/battery_dt_course_project_1080p.mp4`（10:55，1080p，
英文旁白 + 内嵌英文字幕；独立字幕 `video/final/battery_dt_course_project.srt`）。
构建说明、章节表与完整讲稿见 `video/README.md` 和 `video/script.md`。

`run_all.py` 会检查 `127.0.0.1:1883`：

- 如果端口已经打开，使用已有的 Mosquitto；
- 如果没有，自动启动项目内的纯 Python `amqtt` broker。因此 **没有 Docker 也能跑**。

也可以用 Docker 启动 Mosquitto：

```bash
docker compose up -d
python scripts/run_all.py --fresh
```

演示时间：默认 profile 是 2 小时城市工况，加速 10 倍，约 12 分钟跑完。短视频/快速联调可以：

```bash
# 6 分钟：20 倍加速
python scripts/run_all.py --fresh --speed 20
# 只跑 5 分钟仿真时间做冒烟测试
python scripts/run_all.py --fresh --speed 20 --duration 300
# 不自动启动 dashboard / simulator
python scripts/run_all.py --fresh --no-dashboard
```

如果要在一个全新的机器上重建环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

当前 `.venv` 使用了系统预装的科学计算包（`--system-site-packages`），但 `requirements.txt`
已经锁定全部依赖，标准 venv 也可以安装。项目内没有绝对路径，换目录后只需重新运行脚本。

## 2. 架构与数据流

```text
                      cmd/load, cmd/fault (QoS1)
        +--------------------------------------------------+
        |                                                  v
 [1 Plant Simulator] -- telemetry 1Hz --> [2 MQTT Broker] --> [4 Twin Engine]
   truth_pack01.csv                         |    |             1RC + EKF + RLS
   (只写本地，不发布)                        |    +--> twin/state, twin/alarm
                                             v
                                  [3 Ingestor -> SQLite]
                                   raw_messages + measurements
                                   twin_outputs + alarms + gaps
                                             |
                                             v
                                  [5 Streamlit Dashboard]
                                  监控 / 告警解释 / what-if
```

| | Plant 模拟器（真实世界） | Twin 模型 |
|---|---|---|
| 电气 | 2RC ECM | 1RC ECM，HPPC 辨识 |
| 内阻 | Arrhenius 温度依赖 + 老化漂移 + 故障乘子 | RLS 慢跟踪 + 残差回归快检测 |
| 热 | 双节点（core / surface） | 单节点 + 代数 core 估计 |
| 噪声 | V ±5 mV、I ±0.05 A、T ±0.5 °C、量化、丢包 | 只看带噪 telemetry |
| 参数 | `config/plant_params.yaml` | `config/twin_params.yaml` |
| truth | `data/truth_pack01.csv` | 不可见 |

`src/battery_dt/simulator/` 是唯一读取 `plant_params.yaml` 的包。Twin 进程不会导入它，
也不订阅任何 truth topic。**truth 文件只用于评估脚本打分。**

## 3. 采集变量

| 变量 | 单位 | 来源 | 频率 |
|---|---|---|---|
| `voltage_V` | V | 分压采样（含噪声和量化） | 1 Hz |
| `current_A` | A（放电为正） | 霍尔传感器 | 1 Hz |
| `surface_temp_C` | °C | NTC 表面温度 | 1 Hz |
| `ambient_temp_C` | °C | 环境温度传感器，保持采样 | 0.1 Hz |
| `seq` | — | 设备序号，用于去重和缺口检测 | 每条消息 |
| `ts` | ISO-8601 UTC | **仿真采集时间** | 每条消息 |

入库时另存 `ts_ingest`（墙钟到达时间）。演示中 `ts` 按加速比前进，数据新鲜度必须看
`ts_ingest`，不能看 `ts`。

假设：电芯完全一致且均衡；单次运行容量不变；OCV-SoC 曲线取自文献；对流系数恒定；忽略迟滞。
这些假设也写在评估报告的“局限”中。

## 4. MQTT 设计

Base topic：`dt/battery/pack01`。全部使用 MQTT，不引入 OPC UA。

| Topic | 发布者 → 订阅者 | 内容 | QoS / 选项 |
|---|---|---|---|
| `.../telemetry` | plant → ingestor, twin | 测量值 | QoS1 |
| `.../meta` | plant → all | 单位、频率、profile | retained |
| `.../status` | plant → dashboard, ingestor | online/offline | QoS1 + retained + LWT |
| `.../twin/state` | twin → dashboard, ingestor | SoC、R0、核心温度、预测、残差、续航 | QoS1 |
| `.../twin/alarm` | twin → dashboard, ingestor | 告警、原因、建议；`active:false` 为解除 | QoS1 |
| `.../cmd/load` | dashboard → plant | 改负载 / 清除覆盖 | QoS1 |
| `.../cmd/fault` | dashboard → plant | 注入/清除故障 | QoS1 |
| `.../whatif/request` | dashboard → twin | 场景评估请求 | QoS1 |
| `.../whatif/response` | twin → dashboard | 场景结果和建议 | QoS1 |

Telemetry 示例：

```json
{"asset_id":"pack01","seq":1532,"ts":"2026-11-08T10:15:32.000Z",
 "voltage_V":46.82,"current_A":12.4,"surface_temp_C":31.6,"ambient_temp_C":24.9}
```

`status` 的 LWT payload 固定为 `offline / reason=lwt`。演示时可以：

```bash
# 终端 1：看所有消息
python scripts/mqtt_monitor.py

# 终端 2：强杀 simulator，触发 LWT
pkill -9 -f src/battery_dt/simulator/publisher.py
```

Dashboard 会在 8 s 内显示数据延迟，15 s 后显示离线；broker 中 retained 的 status 也会变成
offline。

Ingestor 使用固定 client id + `clean_session=False`，重启后可继续使用 broker 的会话。QoS1 下
正常断线不会主动丢消息。

## 5. 数据管理

SQLite 单文件：`data/battery_dt.db`。打开 WAL；写入采用单连接 + 0.5 s 批量提交，避免在慢文件系统
上每条消息 fsync 一次。

| 表 | 作用 |
|---|---|
| `raw_messages` | 原始 JSON、topic、到达时间，保证可追溯 |
| `measurements` | 窄表：`asset_id, variable, value, unit, ts_source, ts_ingest, seq, quality` |
| `twin_outputs` | 每次孪生更新的完整输出 |
| `alarms` | 告警触发/解除记录，含原因、建议、证据 JSON |
| `data_gaps` | 按 `seq` 检测到的丢包缺口 |
| `commands` | 负载、故障和 what-if 请求/响应留痕 |
| `asset_status`, `asset_meta`, `runs` | 状态、元数据和配置快照 |

处理流程：

1. Schema 和单位校验；
2. 量程校验（V 30–58 V、I ±60 A、表面温度 −20–100 °C 等），越界标 `invalid`；
3. `(asset_id, run_id, seq, variable)` 唯一约束去重；
4. 按 `seq` 检测缺口，写入 `data_gaps`，缺失不填 0；
5. 模型使用前可 `align_to_grid(..., freq="1s")` 对齐，缺失保留 `NaN`；
6. 原始消息与清洗后的窄表分开保存。

查询/导出：

```bash
python scripts/query_db.py --variable voltage_V --limit 20
python scripts/query_db.py --variable voltage_V --csv /tmp/voltage.csv
```

等价 SQL：

```sql
SELECT variable, value, unit, ts_source, ts_ingest, quality
FROM measurements
WHERE asset_id = 'pack01' AND variable = 'voltage_V'
ORDER BY ts_source DESC LIMIT 100;
```

索引：`(asset_id, variable, ts_source)`、`(asset_id, ts_source)`、`(ts_ingest)`。

## 6. 模型与更新机制

### Plant（数据生成侧，刻意更复杂）

- 2RC：`V = OCV(SoC) − I·R0 − V1 − V2`，两个 RC 支路解析离散更新；
- `R0(T) = R0_ref · exp(Ea/R · (1/T − 1/T_ref))`，再乘老化漂移和故障乘子；
- 双节点热模型：core ↔ surface ↔ ambient；
- 测量噪声、量化、0.5% 丢包（可配置）、电压/电流传感器故障；
- aging：R0 随累计 Ah 缓慢增长，容量轻微衰减。

### Twin（部署侧，刻意简化）

- 1RC：`V = OCV(SoC) − I·R0 − V1`，`dV1/dt = −V1/(R1C1) + I/C1`；
- 单热节点：`Cth·dT/dt = I²R0 + I·V1 − hA·(T − Tamb)`；
- EKF 状态 `[SoC, V1, T_surface]`，观测量 `[V, T_surface]`；
- 每步使用 **pre-fit innovation** 做异常检测，再更新状态；
- RLS 慢速跟踪 R0；另有 45 s 窗的 `residual = offset + slope·I` 回归，把
  “电流相关的电压降”与“与电流无关的传感器偏置”区分开，用于快速故障分类；
- R0 健康度取慢估计和快速回归的较大值，并对已确认的电阻故障做缓慢 latch，避免告警闪烁；
- 剩余续航用最近 600 s 平均电流做恒流外推；what-if 使用用户输入的未来电流/环境温度。

### 参数辨识

`scripts/identify_params.py` 先让 plant 生成 HPPC **测量日志**（只含 V/I/T，不含 truth），
然后用 `scipy.optimize.least_squares` 拟合 1RC 电气参数和单节点热参数：

```bash
python scripts/identify_params.py
```

结果写入 `config/twin_params.yaml` 和 `reports/identification_metrics.csv`。
本次辨识结果：HPPC 电压 RMSE 约 **8.8 mV**，最大误差 **29.5 mV**。

### 已量化的结果（详见 `reports/results.md`）

| 测试 | 结果 |
|---|---|
| T1 模型精度（未参与辨识的工况） | 电压 RMSE **13.0 mV**，最大 **42.1 mV**；无 RC 对照 285.9 mV |
| T2 SoC（初值错 35 个百分点） | **6 s** 收敛到 ±2%，收敛后 RMSE **0.11%**；库仑计数 RMSE 35% |
| T3 续航 | 2 h 工况 MAPE **4.23%**；线性电压外推基线 **104%** |
| T4 异常 | 正常 1 h **0 误报**；R0 +50% 延迟 63 s，冷却失效 352 s，传感器 +0.5 V 1 s |
| T5 鲁棒性 | 5% 丢包 + 噪声加倍：SoC RMSE 0.097% → 0.108%，电压残差 RMS 8.5 → 16.4 mV |

T4 的阈值只用正常数据确定（正常残差 99.5 分位等），故障数据只用于计算延迟。
冷却失效测试中先施加 18 A 负载，使热故障在合理时间内显现；若仅按城市工况低负载，
热时间常数会令检测延迟变长。

## 7. 用户服务（Streamlit）

Dashboard 不是“只画曲线”，三个页面分别对应看、判断、决策：

1. **监控**：实测/预测电压叠加、SoC、SoH、核心温度、剩余续航、数据新鲜度；
2. **异常与解释**：活动告警卡片包含原因和建议；EKF pre-fit 残差、R0 比率、SoC 一致性；
3. **What-if 决策**：输入未来电流、持续时间和环境温度，Twin 从当前状态前向仿真，返回
   到截止电压时间、到温度上限时间、峰值温度、建议最大电流和中文建议；
4. **数据管理**：表计数、最近点、CSV 导出、SQL 示例。

侧边栏还可以：

- 设置恒流负载（`cmd/load`）；
- 注入 R0 +50%、冷却失效、电压传感器 +0.5 V；
- 清除故障。

热故障建议把负载设到 15–20 A 再注入，否则热时间常数使温度上升很慢。R0 故障的快速分类需要
电流有变化；如果一直维持恒定电流，电阻增加与电压传感器偏置在短时间内不可区分。

## 8. 现场演示流程（约 13 分钟）

1. 画问题、用户、三个决策问题（还能跑多久 / 是否在劣化 / 会不会过热）。
2. 起身展示架构、变量表、plant vs twin 表。
3. `python scripts/run_all.py --fresh`，Dashboard 打开。
4. 另一终端 `python scripts/mqtt_monitor.py`，展示 telemetry、twin/state、status、meta。
5. 展示 SoC 从错误初值 0.60 收敛到约 0.95（DB 历史曲线）。
6. 侧边栏把负载改为 18 A / 10 min → 观察电流和续航预测改变；说明“新数据更新输出”。
7. 注入冷却失效（先在 18 A 负载下），30 s 至几分钟后出现 THERMAL_ANOMALY，展示原因和建议。
8. 用 `pkill -9 -f src/battery_dt/simulator/publisher.py` 触发 LWT，Dashboard 变红。
9. 切到 What-if，输入 20 A / 30 min / 35 °C，展示建议电流和预测时间。
10. 打开 `reports/results.md` 和图表，讲 T1–T5 指标、阈值标定方式和局限。

故障 R0 演示时先不要施加恒流覆盖，保持城市工况的电流变化；否则它会被识别成电压异常，
直到工况重新出现电流变化才转为 RESISTANCE_ANOMALY。这一点也写在局限里。

## 9. 运行评估与测试

```bash
python scripts/identify_params.py --reuse-log
python scripts/evaluate.py
python -m pytest -q
```

- `reports/results.md`：T1–T5 表格、阈值、局限；
- `reports/figures/`：评估图；
- `reports/identification_metrics.csv`：HPPC 辨识指标；
- 测试覆盖 OCV/ECM、预处理、EKF/SoC 收敛、what-if、SQLite 去重、MQTT QoS1/retained 往返；
  当前 **13 个测试全部通过**。

评估脚本在进程内运行 plant 和 twin。truth 保存在独立 DataFrame 中，twin 的 `step()` 只接收
telemetry；评估结束后才按 `seq` 合并用于打分。

## 10. 目录

```text
battery_dt/
├─ README.md
├─ requirements.txt
├─ docker-compose.yml
├─ config/
│  ├─ mosquitto.conf
│  ├─ system.yaml          # topic、频率、加速比、阈值
│  ├─ plant_params.yaml    # 仅 simulator 读取
│  └─ twin_params.yaml     # HPPC 辨识结果
├─ data/
│  ├─ ocv_curve.csv
│  ├─ profiles/
│  ├─ battery_dt.db        # 运行时生成
│  └─ truth_pack01.csv     # 运行时生成，仅评估用
├─ src/battery_dt/
│  ├─ common/              # config、MQTT、OCV、时间
│  ├─ simulator/           # 2RC + 双节点热模型 + publisher
│  ├─ storage/             # 校验、去重、对齐、SQLite、ingestor
│  ├─ twin/                # ECM、thermal、EKF、RLS、异常、预测、service
│  └─ dashboard/           # Streamlit
├─ scripts/
│  ├─ broker.py            # 无 Docker 时的嵌入式 amqtt
│  ├─ run_all.py
│  ├─ identify_params.py
│  ├─ evaluate.py
│  ├─ mqtt_monitor.py
│  ├─ query_db.py
│  └─ generate_data.py
├─ tests/
├─ reports/                 # results.md + 5 张评估图
├─ video/                   # 幻灯片、旁白、录屏、最终 MP4/SRT
│  ├─ final/battery_dt_course_project_1080p.mp4
│  └─ README.md / script.md
└─ logs/                    # 运行时日志
```

## 11. 主动说明的局限

- 1RC 在低 SoC、低温、大倍率脉冲下误差会增大；当前验证覆盖 20–35 °C。
- 没有真实电池实验，plant/twin 差异是刻意构造的，但仍属于仿真验证。
- 电芯被当作完全一致，无法检测单体失衡或局部热点。
- 传感器小偏置（如 0.2 V）与 SoC 变化在短时间内不可区分；演示使用 0.5 V 阶跃。
- R0 故障的快速分类依赖电流变化；恒流下会被归为电压异常。
- 阈值只在一个正常工况族上标定，换工况需重新标定。
- SQLite 适用于单资产演示，不适合多车队高并发写入。
- MQTT 只使用单 broker；没有做 broker 集群或持久化会话的生产级验证。

## 12. 排障

- **端口 1883 被占用**：`run_all.py` 会直接复用；如果已有 broker 配置不同，先停掉，或用
  `--port 1884` 启动嵌入式 broker（run_all 会通过环境变量把端口传给子进程）。
- **没有 `mosquitto_sub` / `sqlite3` CLI**：用 `scripts/mqtt_monitor.py` 和
  `scripts/query_db.py`。
- **Dashboard 空白**：看 `logs/dashboard.log`；确认 broker、ingestor、twin、simulator 顺序。
- **数据库无数据**：`logs/ingestor.log` 会打印 seq、行数和缺口；检查 broker 端口。
- **PyPI 连接失败**：使用上面的清华镜像命令。
- **模拟器停止后 Dashboard 变红**：这是预期的数据过期/LWT 行为，不是故障。

## 13. 课程视频成品

`video/final/battery_dt_course_project_1080p.mp4` 已生成：

- 10 分 55 秒，1920×1080，H.264/AAC；
- 英文技术旁白（Edge TTS，`en-US-AndrewNeural`）+ 内嵌英文字幕；
- 11 页幻灯片 + 约 2 分 25 秒真实 Streamlit/MQTT 现场录屏；
- 录屏覆盖负载命令、热故障、告警解释、what-if、SQLite 数据页、LWT 离线/数据过期；
- 同目录有独立 `.srt`、缩略图、章节表、`video_meta.json`；完整讲稿在 `video/script.md`。

视频不是运行时依赖，提交/运行时可以只带 `video/final/`。若要重新生成：

```bash
.venv/bin/pip install -r video/requirements-video.txt
.venv/bin/python video/build_slides.py
.venv/bin/python video/tts.py
.venv/bin/python video/record_demo.py
.venv/bin/python video/assemble.py
.venv/bin/python video/build_script.py
```

录屏时使用 `--fresh --speed 20`，先等待 66 s 让初始收敛瞬态离开图表，再执行负载/故障/
what-if/LWT 操作。`video/frames_demo/` 和 `video/segments/` 是可再生的中间文件，不进入提交 ZIP。
