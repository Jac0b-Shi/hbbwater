# 告警链路只读审计报告

> 审计范围：当前仓库（`main` 分支，含未提交变更）
> 审计目的：验证 A5151/58362 雨量数据语义、`dry_run`/`NoopPumpController` 调用链、单位/阈值/泵容量字段语义，识别安全语义冲突
> 审计约束：未修改任何代码

---

## 1. 数据来源与语义审计

### 1.1 天气站配置与角色

**证据位置**：`backend/app/services/schema.py:21-36`

```python
DEFAULT_WEATHER_STATIONS = (
    {"station_id": "A5151", "station_name": "宝山大场上大附中", "role": "primary", ...},
    {"station_id": "58362", "station_name": "宝山", "role": "backup", ...},
)
```

- `A5151` 被标记为 `primary`，`58362` 被标记为 `backup`。
- 角色可通过环境变量 `ZTQ_RAINFALL_STATIONS` 覆盖。

### 1.2 实况与预报数据的采集方式

**证据位置**：`backend/app/services/weather.py:355-382`、`250-254`

`ZtqWeatherClient.fetch_station_payloads` 对每个配置站点同时请求两个接口：
- `fycx_trend_sta#2_{station_id}_10`：返回趋势数据，包含 `sk_list`（实况）和 `yb_list`（预报）
- `fycx_sstq#{station_id}`：返回实时天气

解析后，每个 `RainfallPoint` 标记为 `data_type="actual"` 或 `data_type="forecast"`，分别写入 `rainfall_actual_hourly` 和 `rainfall_forecast_hourly`。

**关键发现**：
- `A5151` 和 `58362` 都会各自产生 `RainfallForecastHourly` 记录。
- 预报数据不是“网格预报映射到校园坐标”，而是来自知天气接口按站点返回的 `yb_list`。
- 因此 `rainfall_forecast_hourly.station_id` 在该实现中等价于“站点预报”，不是网格预报降尺度结果。

### 1.3 预报告警中的雨量站选择逻辑

**证据位置**：`backend/app/services/forecast_alerts.py:251-282`

```python
async def _select_station_id(...):
    if requested_station_id:
        return requested_station_id
    stations = (
        select(WeatherStation)
        .where(WeatherStation.is_active == True)
        .order_by(WeatherStation.role.desc(), WeatherStation.station_id)
    )
    ...
    for station in stations:
        count = await db.scalar(
            select(func.count())
            .select_from(RainfallForecastHourly)
            .where(... hour_time in future window ...)
        )
        if count:
            return station.station_id
    return stations[0].station_id
```

**关键发现**：
- 按 `role.desc()` 排序，正常情况会先检查 `primary`（A5151），再检查 `backup`（58362）。
- **但未强制 A5151 优先**：如果 A5151 在未来窗口内无预报数据，而 58362 有，则自动选择 58362，**且不会标记 `rain_source_degraded`**。
- 与深度报告要求的“`A5151` 不可用时显式进入降级模式”不一致。
- 没有区分“实况主源”与“预报主源”。当前实现中，预报数据同样来自 A5151/58362 的站点预报，不是独立网格预报源。

### 1.4 实况雨量在预报模型中的使用

**证据位置**：`backend/app/services/forecast_alerts.py:304-318`

```python
async def _actual_total(db, station_id, ..., hours: int) -> float:
    start_time = now_hour - timedelta(hours=hours)
    total = await db.scalar(
        select(func.sum(RainfallActualHourly.rainfall_mm))
        .where(RainfallActualHourly.station_id == station_id)
        ...
    )
```

**关键发现**：
- `api_24h` 和 `api_72h` 的累计实况雨量来自 `_select_station_id` 返回的同一个 `station_id`。
- 如果预报站降级到 58362，实况累计也会跟随使用 58362，进一步放大站点差异影响。
- 没有独立的“实况主源=A5151，预报主源按配置/质量选择”的拆分逻辑。

---

## 2. 调用链审计

### 2.1 实时告警调用链

**入口**：
- `POST /api/sensors/data` → `backend/app/routers/sensors.py:519-549`
- `POST /api/sensors/webhook/{token}` → `routers/sensors.py:605-639`
- `POST /api/sensors/group-webhook/{token}` → `routers/sensors.py:642-693`

**流程**：
1. `build_sensor_reading` / `build_group_sensor_reading` → 计算 `water_level`（统一为 cm）
2. `infer_ultrasonic_status(sensor, water_level)` → 根据 `warning_level/danger_level` 和 `threshold_condition` 判断 `warning` / `danger`
3. `handle_sensor_reading_alerts` → `backend/app/services/alerting.py:196-207`
4. `_handle_ultrasonic_alerts` → 若 status 为 `warning`/`danger`，生成 `high_water` 告警
5. `_upsert_active_alert` → 应用冷却策略，写 `Alert`，调用 `dispatch_alert_notifications`

**关键发现**：
- 实时告警只依赖单传感器和传感器自身的 `warning_level/danger_level`。
- 没有双传感器一致性校验，没有数据质量标记，没有雨量辅助确认。

### 2.2 预报告警调用链

**入口**：
- 定时触发：`rainfall_collector_loop` → `run_scheduled_forecast_evaluation`（`weather.py:809-830`）
- 手动触发：`POST /api/forecast-alerts/evaluate`（`routers/forecast_alerts.py:65-81`）

**流程**：
1. `evaluate_forecast_alerts` → 创建 `ForecastPredictionRun`
2. 若 `dry_run=False` 且全局启用，则对每个超声波传感器：
   - 调用 `_compute_prediction`
   - 写 `ForecastPredictionResult`
   - 调用 `_handle_forecast_alert_lifecycle` → 创建/更新 `Alert(alert_type="forecast_high_water")`
   - 调用 `dispatch_alert_notifications`

**关键发现**：
- `dry_run=True` 时：不写 `Alert`，不通知，但仍写 `ForecastPredictionRun` 和 `ForecastPredictionResult`。
- `dry_run=False` 时：必须全局启用（`forecast_alert_enabled`）且传感器 profile 启用，才会生成告警。
- `NoopPumpController` 始终返回 `mode=recommendation_only`，不区分 dry_run。

### 2.3 `dry_run` 与 Shadow Mode 的关系

**证据位置**：`backend/app/services/forecast_alerts.py:675-785`、`backend/app/services/pump_control.py`

```python
async def evaluate_forecast_alerts(..., dry_run: bool = True, ...):
    ...
    if not dry_run and not global_config["enabled"]:
        run.status = "skipped"
        ...
    for sensor in sensors:
        ...
        prediction = await _compute_prediction(...)
        result = ForecastPredictionResult(...)
        ...
        if not dry_run:
            alert, notification_sent = await _handle_forecast_alert_lifecycle(...)
```

```python
class NoopPumpController:
    async def build_recommendation(self, context):
        return {
            "mode": "recommendation_only",
            "executable": False,
            ...
        }
```

**关键发现**：
- `dry_run` 当前语义是“是否创建 Alert 和发送通知”，不是“是否执行泵控”。
- 泵控始终为 `recommendation_only`，没有真正的 Auto Mode 开关。
- 因此系统当前实际上处于“永远的 Shadow Mode”——只是这个 Shadow Mode 没有显式标记和版本控制。
- 一旦未来接入 `PlcPumpController`，需要额外状态机来区分：
  - `shadow`：输出建议，不执行
  - `auto`：满足条件时执行
  - `manual`：人工接管
  - `emergency`：人工强制

---

## 3. 单位、阈值与泵容量字段语义审计

### 3.1 传感器字段

| 字段 | 类型 | 单位 | 语义 | 位置 |
|---|---|---|---|---|
| `Sensor.water_level`（读数） | DECIMAL(10,2) | cm | 传感器到水面距离 | `models.py:153` |
| `Sensor.warning_level` | DECIMAL(10,2) | cm | 阈值判定值 | `models.py:91` |
| `Sensor.danger_level` | DECIMAL(10,2) | cm | 阈值判定值 | `models.py:92` |
| `Sensor.threshold_condition` | String(32) | - | `greater_or_equal` / `less_or_equal` | `models.py:93` |
| `Sensor.water_level_baseline` | DECIMAL(10,2) | cm | 基准测距，用于计算 `h_start_mm` | `models.py:95` |

**关键语义**：
- 超声波传感器中，`water_level` 越小表示真实水位越高。
- 当 `threshold_condition="less_or_equal"` 时，正确配置应为 `warning_level > danger_level`。
- 例如：预警水位=91.2 cm，危险水位=81.2 cm（对应首次越堤线）。
- 当前 UI 默认 `threshold_condition="greater_or_equal"`，这对超声波传感器是反向的，需手动调整。

### 3.2 预报告警字段

| 字段 | 类型 | 单位 | 语义 | 位置 |
|---|---|---|---|---|
| `ForecastAlertProfile.warning_rise_mm` | DECIMAL(10,2) | mm | 预测上涨量预警阈值 | `models.py:331` |
| `ForecastAlertProfile.critical_rise_mm` | DECIMAL(10,2) | mm | 预测上涨量危险阈值 | `models.py:332` |
| `ForecastPredictionResult.predicted_free_rise_mm` | DECIMAL(10,2) | mm | 无泵等效上涨量 | `models.py:385` |
| `ForecastPredictionResult.predicted_observed_rise_mm` | DECIMAL(10,2) | mm | 考虑泵削峰后上涨量 | `models.py:386` |
| `ForecastPredictionResult.projected_distance_cm` | DECIMAL(10,2) | cm | 预测未来最低测距 | `models.py:387` |
| `ForecastPredictionResult.latest_distance_cm` | DECIMAL(10,2) | cm | 最新测距 | `models.py:388` |

### 3.3 泵容量字段与模型参数

**证据位置**：`backend/app/services/forecast_alerts.py:48-60`、`461-479`

```python
DEFAULT_MODEL_PARAMS = {
    "pump_on_rise_mm": 50.0,
    "pump_capacity_mm_per_min": 1.05,
    ...
}
```

```python
pump_on_rise_mm = _to_float(model_params.get("pump_on_rise_mm"), 50.0)
pump_capacity_mm_per_min = _to_float(model_params.get("pump_capacity_mm_per_min"), 1.05)
...
pump_active = observed_level > pump_on_rise_mm
pump_output_mm = pump_capacity_mm_per_min * 60  # 转换为 mm/h
observed_level = max(0.0, observed_level - pump_output_mm)
```

**关键发现（严重语义冲突）**：
- `pump_capacity_mm_per_min = 1.05 mm/min` → 乘以 60 得 `63 mm/h = 6.3 cm/h`。
- 该数值与深度报告 `q2 ≈ 6.23 cm/h`（两泵共同净降深）高度吻合。
- 但字段名 `pump_capacity_mm_per_min` 和变量名暗示这是“单泵每分钟容量”，而代码实际把它当作与泵数量无关的常数净降深使用。
- 当前模型没有 `pump_count` 概念。无论实际开几台泵，都减去同一个 `pump_output_mm`。
- 如果未来实现多泵分级，绝不能写成 `pump_count * pump_capacity_mm_per_min`，否则两泵时会被算成 12.6 cm/h，直接翻倍错误。

### 3.4 当前默认阈值与报告推荐值对比

| 参数 | 当前默认值 | 深度报告推荐 | 冲突说明 |
|---|---|---|---|
| `pump_capacity_mm_per_min` | 1.05 mm/min | 对应 q2=6.23 cm/h | 名字误导，且未按泵数区分 |
| `pump_on_rise_mm` | 50 mm | - | 无物理依据，属硬编码 |
| `warning_rise_mm` | 120 mm | - | 无物理依据 |
| `critical_rise_mm` | 250 mm | - | 无物理依据 |
| 越堤裕度 | 未建模 | 002: 81.2 cm；003: 70.6 cm | 系统仍用 `warning_level/danger_level` 原始阈值 |

---

## 4. 关键语义冲突汇总

### 冲突 1：`danger_level` 被超载为“首次越堤阈值”

- 用户已将生产环境的 `danger_level` 设置为接近首次越堤线的值（如 81.2 cm / 70.6 cm）。
- 但字段名和 UI 标签为“危险水位”，没有明确说明这是“首次越堤阈值”还是“危险告警阈值”。
- 缺少字段：`overflow_level_cm`（越堤阈值）、`overflow_confidence`（临时/已标定）、`margin_to_overflow_cm`（动态裕度）。

### 冲突 2：`pump_capacity_mm_per_min` 名不副实

- 实际是“当前泵态下的净降深速率”，不是“每台泵容量”。
- 建议改名为 `net_drawdown_rate_mm_per_min` 或按泵数配置 `drawdown_by_pump_count`。

### 冲突 3：`dry_run` 与 Shadow Mode 语义混杂

- `dry_run` 控制是否发通知，不控制是否执行泵控。
- 系统目前永远是 Shadow Mode，但没有显式状态字段。
- 未来加入自动控制后，需要独立状态机。

### 冲突 4：预报与实况源未分离

- `_select_station_id` 同时决定预报和实况累计的站点来源。
- 如果预报降级到 58362，实况累计也跟随降级，违反“A5151 实况主源”原则。

### 冲突 5：模型输出与策略下限未分离

- 当前 `segmented_pressure_v1` 中，“暴雨事件下限”逻辑直接修改 `peak_free` 和 `peak_observed`，未来无法区分是模型预测还是安全策略强制提升。
- 建议拆分为 `model_risk` 和 `policy_floor`。

### 冲突 6：缺少传感器健康维度

- 实时告警只根据 `water_level` 触发，没有传感器一致性、跳变、数据质量维度。
- 预报告警也没有传入传感器质量标记。
- 建议告警结构增加 `hazard_level` 和 `sensor_health` 两个独立维度。

---

## 5. 最小安全改造顺序建议

基于以上审计，建议按以下顺序实施，避免语义冲突导致误报、漏报或未来 PLC 误动作：

### 第一步：冻结语义（WP0）

1. 定义字段语义文档：
   - `water_level`：cm，传感器到水面距离，越小越危险
   - `warning_level/danger_level`：cm 阈值，用于实时告警；不直接等同于越堤线
   - 新增 `overflow_level_cm`：cm，首次越堤阈值（002: 81.2，003: 70.6，标记为临时/已标定）
   - 新增 `margin_to_overflow_cm`：动态计算，只读
   - `pump_capacity_mm_per_min` 重命名为 `net_drawdown_rate_mm_per_min` 或按泵数配置
   - `dry_run` 保持“是否生成通知”语义；新增 `pump_control_mode`（shadow/auto/manual）
2. 区分实况主源与预报主源：
   - 实况主源固定为 `A5151`
   - 预报主源优先 `A5151`，缺测时降级到 `58362` 并标记 `rain_source_degraded`
3. 在 `ForecastPredictionResult` 中增加 `quality_flags` 和 `model_risk`/`effective_risk`/`policy_reason` 字段

### 第二步：数据质量层（WP1.1、WP1.2、WP1.3）

1. 在 `forecast_alerts.py` 中强制 A5151 优先，并显式记录降级。
2. 实现 002/003 仿射残差计算，但**仅记录和展示，不抑制实时高水位告警**；改为同时生成：
   - 高水位待确认告警（hazard_level）
   - 传感器一致性故障告警（sensor_health）
3. 实现单步跳变检测和质量标记。

### 第三步：模型层（WP2）

1. 新增 `overflow_level_cm` 字段并回填生产值。
2. 将预测模型从 `segmented_pressure_v1` 升级为 `water_level_forecast_v0.5`：
   - 输入：A5151 实况/预报、当前越堤裕度、双传感器最小裕度、净降深参数
   - 输出：预测裕度、预计越堤时间、无泵/当前泵态/全泵三种场景
   - 拆分 `model_risk` 与 `policy_floor`
3. 将泵效参数改为按泵数配置，明确 `q2=6.23 cm/h` 是两泵净降深，不是单泵容量。

### 第四步：控制层（WP3）

1. 新增 `pump_control_mode` 全局配置，默认 `shadow`。
2. 在 `shadow` 模式下，所有控制建议标记为 `executable=False`。
3. 实现 `PumpStateLog` 概率化反演（0/1/2/3 概率分布），区分 `observed` / `inferred` / `manual`。
4. 实现 L0–L3 分级建议，但允许返回 `UNKNOWN` / `HOLD_MANUAL`。

### 第五步：通知与前端（WP4）

1. 实时告警、预报告警、传感器故障使用独立通知模板。
2. 前端展示：雨量源是否降级、传感器一致性状态、预计越堤时间、L0–L3 建议。

### 第六步：验证与上线（WP5）

1. 使用导出 CSV 做离线回放。
2.  Shadow Mode 运行，累积人工操作对照数据。
3. 等泵效参数和越堤阈值物理标定后，才允许讨论 Auto Mode 开启条件。

---

## 6. 证据文件索引

| 文件 | 关键行号 | 说明 |
|---|---|---|
| `backend/app/services/schema.py` | 21-36 | 默认天气站配置（A5151 primary，58362 backup） |
| `backend/app/services/weather.py` | 250-267、355-382、809-830 | 实况/预报采集解析、定时触发预报评估 |
| `backend/app/services/forecast_alerts.py` | 48-60、251-282、304-318、461-479、675-785 | 模型参数、雨量站选择、实况累计、泵效计算、评估流程 |
| `backend/app/services/alerting.py` | 85-258、196-258 | 实时超声波告警逻辑 |
| `backend/app/services/pump_control.py` | 1-48 | NoopPumpController，当前只返回建议 |
| `backend/app/routers/sensors.py` | 519-549、605-693 | 传感器数据接收入口 |
| `backend/app/routers/forecast_alerts.py` | 65-81 | 手动预报评估入口 |
| `backend/app/models.py` | 83-120、181-204、323-404 | Sensor、Alert、ForecastAlertProfile 等模型 |
| `frontend/src/views/Sensors.vue` | 249-265、360-371 | 阈值配置 UI 和默认提示 |
| `frontend/src/views/SensorDetail.vue` | 32-34 | 传感器详情展示阈值 |

---

## 7. 结论

1. **A5151 主源策略在预报链路中未强制实施**：`_select_station_id` 会在 A5151 无预报数据时静默切换到 58362，且不会标记降级。
2. **实况与预报源未分离**：预报降级会连带导致实况累计也使用 58362。
3. **`pump_capacity_mm_per_min` 字段名严重误导**：当前值 1.05 mm/min 实际对应深度报告 `q2=6.23 cm/h` 的两泵净降深，不是单泵容量。
4. **`danger_level` 被超载为越堤阈值**：缺少独立的 `overflow_level_cm` 和裕度字段，语义不清。
5. **`dry_run` 不是 Shadow Mode**：当前系统永远是“建议-only”模式，但缺少显式状态机和版本控制。
6. **实时告警无数据质量维度**：单传感器越阈值即可触发，没有双传感器一致性校验、跳变检测或质量标记。
7. **模型输出与策略下限未分离**：暴雨事件下限直接修改预测结果，不利于后续归因和模型迭代。

**最优先修复项**：
1. 强制 A5151 实况主源，拆分预报主源选择逻辑；
2. 重命名/重构泵效参数，避免将 `q2` 误用为单泵容量；
3. 引入传感器健康维度，但**不能**用传感器不一致直接抑制高水位告警；
4. 新增 `overflow_level_cm` 和 `pump_control_mode` 字段，冻结核心语义后再实施模型改造。
