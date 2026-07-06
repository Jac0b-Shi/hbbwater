# 校园水浸监测告警链路优化工作方案

> 编制依据：
> - `docs/rainfall-waterlevel-report-portable/rainfall-waterlevel-report-v8.md`（深度研究报告）
> - 当前工作区未提交变更（forecast-alerts 子系统、 pump_control 骨架、前端 Settings/Alerts 扩展）
> - 最近一次提交 `6a878f5 feat: add rainfall history and mobile responsive updates`
> - 现场导出数据：`sensor_data_ultrasonic_002/003_20260706.csv`、`rainfall_history_A5151/58362_20260706.csv`

## 1. 目标与范围

本次优化以“告警链路”为主线，覆盖从数据输入、风险评估、告警生成到通知触发的完整路径，目标：

1. **统一雨量源口径**：建模与触发必须以 A5151 为主，58362 仅作背景校验与降级参考。
2. **从固定阈值升级为剩余安全裕度**：将告警触发从“传感器原始读数越线”改为“距首次越堤/危险淹没的剩余高度 + 上涨趋势”。
3. **引入双传感器一致性诊断**：把 002↔003 的仿射残差作为告警链路中的传感器健康标志。
4. **建立预报-实时双轨告警**：预报告警用于提前数小时预触发，实时告警用于已发生的越线/离线/浸水事件；两者在通知渠道、收敛策略上解耦。
5. **为泵组自动控制预留安全边界**：当前版本保持“只建议、不执行”，但告警链路需输出分级的泵控建议（L0–L3）并记录事件台账。
6. **兼容 GB 50014-2021 的自动化与故障安全要求**：控制方式、状态反馈、降级策略、数据台账等可验收。

## 2. 当前告警链路现状

```text
[传感器读数] → backend/app/services/alerting.py
                    ├── high_water（实时阈值）
                    ├── water_detected（浸水）
                    ├── sensor_offline
                    └── low_battery

[雨量采集] → backend/app/services/weather.py:rainfall_collector_loop
                    └── 每次采集后触发 run_scheduled_forecast_evaluation
                         → backend/app/services/forecast_alerts.py
                              └── forecast_high_water（预报型告警）

[告警] → backend/app/services/notifications.py
            ├── 邮件通知（forecast_high_water 已加入中文映射）
            └── Webhook（企业微信/通用）
                  └── forecast_high_water 额外输出 prediction 块

[前端] → Alerts.vue（实时/预报双页签） + Settings.vue（预报配置）
```

已具备的能力：

- 实时阈值告警（`high_water`）按传感器配置的 `warning_level` / `danger_level` 触发，支持 `greater_or_equal` / `less_or_equal` 两种比较方式。
- 告警收敛：按 `alert_type + severity` 在最近 `alert_cooldown_minutes` 分钟内合并。
- 预报告警：每 10 分钟随雨量采集触发，使用 `segmented_pressure_v1` 模型评估未来 6 小时风险。
- 泵控接口：已定义 `PumpController` 协议与 `NoopPumpController`，当前只生成建议不执行。
- 通知渠道：邮件 + Webhook，预报告警已支持预测字段透传。

主要不足：

- 雨量源选择未强制 A5151 优先；`_select_station_id` 逻辑为“任一有预报数据的活跃站点”，存在误用 58362 的风险。
- 预报模型是固定参数经验模型，未结合报告中的 `q2=6.23 cm/h`、面积 `31,762 m²`、当前自由容积等关键数据。
- 缺少双传感器一致性（002↔003 仿射残差）判断，也未把残差异常纳入告警或降级。
- 没有“越堤安全裕度”计算，仍然依赖原始读数阈值；告警阈值未更新到 81.2/70.6 cm 的临时首次越堤参考。
- 没有 0/1/2/3 台泵状态跟踪，也没有 L1–L3 分级控制建议。
- 通知策略未区分实时告警与预报告警的紧急程度；预报告警可能产生重复骚扰。
- 缺少数据质量标记（雨量缺测、传感器跳变、单点异常）在告警链路中的降级处理。
- 缺少“Shadow Mode / 自动模式”开关，无法在生产中安全演练。

## 3. 优化方案（分三个阶段）

### 阶段一：数据质量与传感器一致性（可立即实施，无需硬件）

#### 3.1 雨量源强制分级与降级

| 场景 | 行为 |
|------|------|
| A5151 正常且未来窗口有预报 | 仅使用 A5151；58362 作为诊断字段输出但不参与触发 |
| A5151 缺测/异常，58362 正常 | 进入 `rain_source_degraded=true`，58362 临时参考，置信度降低，优先依赖水位阈值 |
| 两站均异常 | 禁用雨量预触发，仅保留水位安全阈值控制，并产生数据源异常告警 |

**工作包：**

1. 在 `backend/app/services/forecast_alerts.py` 中改造 `_select_station_id`：
   - 显式优先返回 `A5151`；若该站未来窗口无预报，则尝试其他 `role=primary` 站点。
   - 58362 仅在 `A5151` 缺测时作为 fallback，且必须标记 `rain_source_degraded`。
2. 在 `ForecastPredictionResult` 的 `features` 中新增 `rain_source_degraded`、`selected_station_role`、`a5151_available`、`58362_available` 等字段。
3. 在模型中当降级时，将 `confidence` 上限下调（建议 `-0.15`），并降低风险等级一个档（除非水位趋势已确认）。
4. 在 `frontend/src/views/Alerts.vue` 预报详情页展示“雨量源降级”标签。

#### 3.2 水位数据质量与跳变检测

**工作包：**

1. 在 `backend/app/services/alerting.py` 或新增 `backend/app/services/sensor_quality.py` 中实现：
   - 单步跳变检测：`abs(Δs) > 3 cm` 在 15 min 内标记为 `spike_candidate`。
   - 年度事实边界：离线训练时 `002 < 70 cm`、`003 < 60 cm` 视为严重异常候选。
   - 在线越堤级：接近 `002≈81.2 cm` / `003≈70.6 cm` 时触发紧急事件，不再等待 70/60。
2. 当单传感器异常而另一传感器正常时，告警链路应：
   - 保持泵的安全状态（已运行则不停泵）；
   - 以正常传感器和 A5151 雨量作为决策依据；
   - 立即发出 `SENSOR_QUALITY_DEGRADED` 诊断告警（ severity=medium ），不阻塞高水位告警。
3. 在 `SensorReading` 的 `raw_data` 或 `status` 字段中写入质量标签：`normal` / `spike` / `out_of_bounds` / `single_sensor_only`。

#### 3.3 双传感器仿射一致性在线监测

**工作包：**

1. 在 `backend/app/services/sensor_quality.py` 中实现 `compute_affine_residual(s002, s003)`，使用报告参数：`expected_003 = 0.9840 * s002 - 9.26`。
2. 在每次收到读数或每次预报评估时，将当前残差 `e_t = s003 - expected_003` 写入 `SensorReading.raw_data` 或独立的传感器一致性日志表。
3. 告警分级：
   - `|e| ≤ 1.0 cm`：正常；
   - `|e| > 1.5 cm` 连续 3 个周期：一致性预警；
   - `|e| > 3.0 cm` 或突变：强异常候选，进入传感器降级模式。
4. 当前端显示水位时，若残差超 1.5 cm，显示“双传感器不一致”提示。

### 阶段二：风险评估模型升级（1–2 周，依赖阶段一数据）

#### 3.4 引入“越堤安全裕度”作为告警触发基准

当前传感器阈值 `warning_level` / `danger_level` 仍按原始读数配置。建议新增“统一高程/裕度”层：

```text
overflow_margin_002_cm = s002 - 81.2   # 临时值，待声轴姿态标定后替换
overflow_margin_003_cm = s003 - 70.6
```

**工作包：**

1. 在 `Sensor` 模型中新增字段：
   - `overflow_level_cm`（首次越堤临时阈值）
   - `critical_inundation_level_cm`（严重淹没线，对应旧的 70/60）
   - `overflow_margin_enabled`（是否启用裕度模式）
2. 在 `backend/app/services/alerting.py` 中新增裕度模式：当启用时，高水位告警基于 `overflow_margin` 计算：
   - `margin ≤ 12 cm`：预警（watch）
   - `margin ≤ 10 cm` 或预计 2h 越堤：L1，建议 1 台泵
   - `margin ≤ 7 cm` 或预计 1h 越堤：L2，建议 2 台泵
   - `margin ≤ 5 cm` 或预计 30min 越堤：L3，建议 3 台泵
   - `margin ≤ 0 cm`：E0 首次越堤，最高级告警
3. 前端 `Alerts.vue` 实时告警详情展示“剩余裕度”。

#### 3.5 预报模型升级：`water_balance_v1`

当前 `segmented_pressure_v1` 使用压力/衰减经验参数，建议替换为与报告一致的水量平衡模型：

```text
Δh_t = g(r_t, h_{t-1}) - q_{n_t} * Δt
```

其中 `g(r_t, h_{t-1})` 用 A5151 当前/滞后/累计雨量驱动；`q_{n_t}` 取 `n_t` 台泵净降深；默认 `q_2 = 6.23 cm/h`，`q_1`、`q_3` 参数化但标定前保守取值。

**工作包：**

1. 在 `backend/app/services/forecast_alerts.py` 中实现 `compute_prediction_water_balance`：
   - 输入：A5151 预报序列、当前水位、面积 `A0=31,762 m²`、泵参数 `q1/q2/q3`。
   - 输出：未来 `horizon_hours` 逐小时水位、越堤时间、风险等级。
2. 将 `pump_params` 扩展为：
   ```json
   {
     "pump_on_margin_cm": 10,
     "q1_cm_per_h": 3.0,
     "q2_cm_per_h": 6.23,
     "q3_cm_per_h": 8.0,
     "min_runtime_minutes": 15,
     "pump_switch_hysteresis_cm": 2
   }
   ```
3. 模型版本字段 `model_version` 升级为 `water_balance_v1`，保留旧版本回滚能力。
4. 在 `Settings.vue` 中允许按传感器配置 `q1/q2/q3`，单位 cm/h。

#### 3.6 泵状态反演与 0/1/2/3 台分级建议

**工作包：**

1. 新增后台服务 `backend/app/services/pump_state_inversion.py`：
   - 读取历史 002/003 读数，检测持续下降段；
   - 在晴天（A5151 过去 6h 累计≈0）且下降速率 ≈ 6.23 cm/h 时标记为 `n_t=2`；
   - 在整点/半点边界检测切换点；
   - 对雨天使用隐状态模型（HMM/DP）同时估计 `n_t` 与 `q1/q2/q3`。
2. 在 `ForecastPredictionResult.control_recommendation` 中输出分级建议：
   ```json
   {
     "mode": "recommendation_only",
     "executable": false,
     "level": "L1",
     "requested_pump_count": 1,
     "reason": "预计 2h 内越堤裕度 ≤ 10 cm",
     "fallback_if_fault": "next_available_pump"
   }
   ```
3. 前端在预报告警详情展示“建议启动泵数”与“原因”。

### 阶段三：通知治理与生产化（1 周，可并行）

#### 3.7 告警收敛与通知分级

**工作包：**

1. 在 `backend/app/services/notifications.py` 中：
   - 实时告警（`high_water`）走最高优先级，邮件+Webhook+短信/语音可选扩展；
   - 预报告警（`forecast_high_water`）在风险等级为 `warning` 时走 Webhook，为 `critical` 时增加邮件；
   - 同一传感器同一风险等级在 `cooldown_minutes` 内只发一次通知，已存在活动告警时不重复创建新告警。
2. 在 `Alerts.vue` 中增加“预报告警忽略/确认”按钮，便于值班人员降噪。
3. 在 `Alert` 模型中新增 `acknowledged_at` / `acknowledged_by` 字段，用于记录人工确认。

#### 3.8 Shadow Mode / 自动模式开关

**工作包：**

1. 在系统配置中新增 `forecast_alert_execution_mode`：
   - `shadow`：只记录预测、建议和模拟告警，不实际通知（除测试接收人）。
   - `advisory`：生成真实告警和通知，但泵控建议仍为 `executable=false`。
   - `auto`（后续阶段）：当 pump_controller 实现真实执行器且通过验收后启用。
2. 当前未提交版本已是 `advisory` 与 `shadow` 的混合（dry_run 可控制），建议把 dry_run 和 mode 解耦：
   - `dry_run` 用于单次评估演练；
   - `execution_mode` 用于全局运行模式。

#### 3.9 事件台账与审计

**工作包：**

1. 新增 `pump_event_log` 表（或复用 `forecast_prediction_runs` / `alerts`）：
   - 每次泵启停命令、接触器反馈、电流、故障、手动/自动模式、操作原因。
2. 在 `backend/app/services/pump_control.py` 中扩展 `build_recommendation` 输出字段，包含 `requested_pump_count`、`actuator_binding_id`、`reason_code`。
3. 前端 `Settings.vue` 和 `Alerts.vue` 增加“事件台账”只读列表。

## 4. 详细工作包与文件映射

| 工作包 | 主要文件 | 预计工时 | 前置依赖 |
|--------|----------|----------|----------|
| 3.1 雨量源强制分级 | `backend/app/services/forecast_alerts.py`, `frontend/src/views/Alerts.vue` | 1d | 无 |
| 3.2 水位数据质量 | 新增 `backend/app/services/sensor_quality.py`, `backend/app/services/alerting.py` | 2d | 无 |
| 3.3 仿射一致性 | `backend/app/services/sensor_quality.py`, `frontend/src/views/Alerts.vue` | 1.5d | 无 |
| 3.4 越堤安全裕度 | `backend/app/models.py`, `backend/app/schemas.py`, `backend/app/services/alerting.py`, `database/*/init.sql` | 2d | 无 |
| 3.5 水量平衡预报模型 | `backend/app/services/forecast_alerts.py`, `frontend/src/views/Settings.vue` | 3d | 3.1, 3.4 |
| 3.6 泵状态反演 | 新增 `backend/app/services/pump_state_inversion.py`, `backend/app/services/pump_control.py` | 3d | 3.5 |
| 3.7 通知分级收敛 | `backend/app/services/notifications.py`, `backend/app/models.py`, `frontend/src/views/Alerts.vue` | 2d | 无 |
| 3.8 Shadow/Auto 模式 | `backend/app/services/system_config.py`, `backend/app/services/forecast_alerts.py`, `frontend/src/views/Settings.vue` | 1.5d | 无 |
| 3.9 事件台账 | 新增/扩展 `database/*/init.sql`, `backend/app/models.py`, `backend/app/services/pump_control.py` | 2d | 3.6 |
| 测试与验收 | `backend/tests/test_forecast_alerts.py`, `backend/tests/test_sensor_quality.py`, `tests/e2e/settings-dashboard.spec.mjs` | 3d | 全部 |

## 5. 数据验证与标定任务（建议同步推进）

告警链路的可靠性受限于输入数据质量，以下任务必须同步安排：

1. **声轴姿态与多水位标定**：测量 002、003 换能器发射面的俯仰/横滚，建立 `H = α + β·s`；至少 3–5 个已知水位点。
2. **岸堤与泵入口标高**：最低岸堤、桥面、泵入口、出水口、下游水位；建立 `A(h)` 或 `V(h)` 曲线。
3. **单泵/双泵/三泵受控试验**：在晴天或可控条件下分别运行 1、2、3 台泵，标定 `q1/q2/q3`。
4. **人工启停台账**：在自动化前，要求每次启停记录时间、台数、操作人；自动化后记录 PLC 命令、接触器反馈、电流。
5. **局地短时雨量升级**：将 A5151 或校园现场雨量升级为 5–10 分钟粒度，支撑真正提前触发。

## 6. 关键设计约束（必须遵守）

1. **雨量源**：A5151 主，58362 辅；禁止默认融合。
2. **传感器异常**：单点跳变、单传感器越线不直接停泵；保持安全状态并用另一传感器/雨量/人工确认决策。
3. **泵控安全**：当前版本保持 `executable=false`，任何真实执行必须等电气保护、就地急停、最低安全水位联锁和验收完成后才能上线。
4. **GB 50014-2021**：永久性工程改造时按规范校核供电负荷等级、泵流量、扬程、集水池容积、检测自动化与故障安全。
5. **顺序启动**：若未来三泵并行，必须错峰启动，禁止同时合闸。

## 7. 验收标准

- [ ] 雨量源选择强制 A5151 优先，58362 仅作为 fallback 并标记降级；相关测试通过。
- [ ] 水位跳变/越界/单传感器异常检测上线，异常读数不导致误告警或误停泵。
- [ ] 002↔003 仿射残差在线计算，超 1.5 cm 连续 3 周期产生一致性预警，并在 UI 展示。
- [ ] 传感器配置支持 `overflow_level_cm` / `critical_inundation_level_cm`，实时告警可基于越堤安全裕度触发。
- [ ] 预报模型支持 `water_balance_v1`，默认使用 `q2=6.23 cm/h`，可配置 `q1/q2/q3`。
- [ ] 泵控建议输出 L0–L3 分级与 requested_pump_count，且不直接执行（`executable=false`）。
- [ ] 通知渠道对实时告警与预报告警分级，同一风险等级在冷却期内不重复通知。
- [ ] Shadow / Advisory / Auto 模式可配置，模式切换有日志审计。
- [ ] 新增 `pump_event_log` 或等效台账，记录命令、反馈、电流、故障、原因。
- [ ] 新增回归测试覆盖传感器质量、水量平衡预报、泵状态反演、通知收敛。

## 8. 风险与依赖

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 未标定 `q1/q3` 导致模型偏差 | 预报模型可能高估/低估泵能力 | 先固定 `q2=6.23`，`q1/q3` 取保守值；受控试验后复标 |
| 声轴姿态未测量，临时阈值不准 | 首次越堤线可能偏差 | 在 UI 和告警中标注“未标定”；将 81.2/70.6 作为临时参考 |
| 58362 误用为主源 | 预报告警可能漏报/误报 | 代码强制 A5151 优先，增加审计字段 |
| 单传感器异常导致误操作 | 泵组误启停 | 异常时保持安全状态，使用多源确认 |
| 通知过度 | 值班疲劳 | 预报告警收敛 + 风险等级分级 + 人工确认 |
| 真实泵控执行过早 | 安全/设备风险 | 当前阶段保持 recommendation_only，电气改造与验收后再启用 executable |

## 9. 建议的近期迭代顺序（最小可运行闭环）

为尽快形成可用闭环，建议按以下顺序交付：

1. **Week 1**：3.1（雨量源） + 3.2（数据质量） + 3.3（仿射一致性） + 3.7（通知收敛）。
   - 目标：消除误报来源，告警链路更可信。
2. **Week 2**：3.4（越堤裕度） + 3.5（水量平衡模型） + 3.8（Shadow/Advisory 模式）。
   - 目标：预报告警从经验模型升级为可解释水力模型，并安全运行。
3. **Week 3**：3.6（泵状态反演） + 3.9（事件台账） + 综合测试验收。
   - 目标：输出分级泵控建议，建立可审计的自动化事件链。
4. **后续**：结合现场标定数据（`q1/q3`、声轴姿态、岸堤标高）复标模型，并评估真实执行条件。

---

*方案生成时间：2026-07-06*
*下次评审点：Week 1 结束后，验证数据质量与通知收敛效果*
