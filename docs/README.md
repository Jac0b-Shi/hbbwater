# 校园水浸监测数据存储与可视化系统

基于双数据库分层存储、Vue + WordPress 前后端分离的完整技术方案。

组 Webhook 转发服务接入请参考 [GROUP_WEBHOOK_PROTOCOL.md](GROUP_WEBHOOK_PROTOCOL.md)。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                          前端层 (Vue 3)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ 监控仪表盘   │  │ 传感器管理   │  │ 历史数据/告警/设置       │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Caddy Web Server                            │
│              (反向代理 / 静态文件 / PHP-FPM)                      │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   FastAPI       │  │   WordPress     │  │  Webhook Proxy  │
│   (API服务)      │  │   (管理后台)     │  │  (数据接收)      │
│  :8000          │  │   /wp           │  │  :8080          │
└────────┬────────┘  └─────────────────┘  └────────┬────────┘
         │                                          │
         │    ┌─────────────────┐  ┌────────────────────────────┐   │
         └───►│ 控制库 SQLite   │  │ 业务库 MySQL / 达梦        │◄──┘
              │ admin_users     │  │ sensor_readings            │
              │ system_config   │  │ sensor_readings_archive    │
              │ business profiles│ │ sensor_summary_* / alerts  │
              └─────────────────┘  └────────────────────────────┘
```

## 项目结构

```
/mnt/e/CodeProjects/hbbwater/
├── backend/                 # FastAPI 后端服务
│   ├── app/
│   │   ├── main.py         # FastAPI 主入口
│   │   ├── models.py       # SQLAlchemy 数据模型
│   │   ├── database.py     # 数据库连接配置
│   │   ├── schemas.py      # Pydantic 数据验证
│   │   ├── routers/        # API 路由
│   │   │   ├── sensors.py  # 传感器API
│   │   │   ├── alerts.py   # 告警API
│   │   │   └── dashboard.py# 仪表盘API
│   │   └── services/       # 业务逻辑
│   ├── requirements.txt    # Python 依赖
│   └── .env.example        # 环境变量示例
├── frontend/                # Vue.js 前端
│   ├── src/
│   │   ├── views/          # 页面组件
│   │   ├── components/     # 通用组件
│   │   ├── stores/         # Pinia 状态管理
│   │   └── router/         # Vue Router
│   ├── package.json
│   └── vite.config.js
├── wordpress/               # WordPress 文件
├── database/                # 数据库脚本
│   ├── init.sql            # 数据库初始化
│   └── procedures.sql      # 存储过程
├── caddy/                   # Caddy配置
│   └── Caddyfile
├── webhook_proxy/           # 传感器数据接收代理
│   ├── webhook_proxy.py
│   └── requirements.txt
└── docs/                    # 文档
    └── README.md
```

## 快速开始

### 1. 初始化数据库

```bash
# 登录 MySQL
mysql -u root -p

# 执行初始化脚本
source /mnt/e/CodeProjects/hbbwater/database/mysql/init.sql
source /mnt/e/CodeProjects/hbbwater/database/mysql/procedures.sql
```

### 2. 启动 FastAPI 后端

```bash
cd /mnt/e/CodeProjects/hbbwater/backend

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 复制环境变量配置
cp .env.example .env

# 启动服务
python -m app.main
# 或使用 uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 启动 Webhook 代理

```bash
cd /mnt/e/CodeProjects/hbbwater/webhook_proxy
pip install -r requirements.txt
python webhook_proxy.py
```

### 4. 启动前端开发服务器

```bash
cd /mnt/e/CodeProjects/hbbwater/frontend
npm install
npm run dev
```

### 5. 启动 Caddy

```bash
cd /mnt/e/CodeProjects/hbbwater/caddy
caddy run --config Caddyfile
```

## 传感器数据格式

### 超声波传感器

```json
{
  "sensor_id": "ultrasonic_001",
  "sensor_type": "ultrasonic",
  "water_level": 85.6,
  "timestamp": "2025-01-20T14:30:00Z",
  "status": "normal",
  "battery_level": 92.1,
  "signal_strength": -45,
  "location": "library_basement"
}
```

### 浸水传感器

```json
{
  "sensor_id": "immersion_001",
  "sensor_type": "immersion",
  "water_detected": true,
  "timestamp": "2025-01-20T14:32:15Z",
  "status": "alarm",
  "duration": 45,
  "location": "server_room",
  "severity": "high"
}
```

## API 接口

### 传感器管理

- `GET /api/sensors/` - 获取传感器列表
- `POST /api/sensors/` - 创建传感器
- `GET /api/sensors/{id}` - 获取传感器详情
- `PATCH /api/sensors/{id}` - 更新传感器
- `DELETE /api/sensors/{id}` - 删除传感器

### 数据接收

- `POST /api/sensors/data` - 接收传感器数据
- `GET /api/sensors/{id}/readings` - 获取传感器读数
- `GET /api/sensors/{id}/timeseries` - 获取时序数据

### 告警管理

- `GET /api/alerts/` - 获取告警列表
- `GET /api/alerts/active` - 获取活动告警
- `POST /api/alerts/{id}/resolve` - 处理告警

### 仪表盘

- `GET /api/dashboard/stats` - 获取统计数据
- `GET /api/dashboard/sensor-status` - 获取传感器状态
- `GET /api/dashboard/recent-readings` - 获取最近读数
- `GET /api/dashboard/alerts/recent` - 获取最近告警

### 天气雨量

- `GET /api/weather/rainfall/summary` - 获取当前实况雨量与未来 1/3/6/24 小时预报累计
- `GET /api/weather/rainfall/history` - 查询实况小时雨量和当前滚动预报小时值
- `GET /api/weather/rainfall/revisions` - 查询实况小时雨量后续修正记录

## 数据库架构

### 分级存储策略

- **热数据** (`sensor_readings`): 最近14天的原始数据，支持高频查询
- **归档数据** (`sensor_readings_archive`): 超过14天的历史数据
- **汇总数据** (`sensor_summary_hourly/daily`): 小时/日统计数据
- **雨量实况** (`rainfall_actual_hourly`): 每个气象站每小时一条最新实况值
- **雨量预报** (`rainfall_forecast_hourly`): 滚动保留当前小时起未来24小时预报值
- **实况修正** (`rainfall_actual_revisions`): 仅记录同站同小时实况值发生变化的修正日志

### 自动维护

- 每小时自动归档过期数据
- 每小时自动计算小时汇总
- 每日自动计算日汇总
- 每10分钟检查离线传感器
- 每小时检查低电量告警

## 配置文件

### 后端环境变量 (.env)

```bash
CONTROL_DATABASE_URL=sqlite+aiosqlite:///./runtime/control.db

BUSINESS_DB_HOST=localhost
BUSINESS_DB_PORT=3306
BUSINESS_DB_NAME=flood_monitoring
BUSINESS_DB_USER=flood_user
BUSINESS_DB_PASSWORD=flood_monitoring_2025

# 达梦服务名模式可改为：
# BUSINESS_DB_DIALECT=dm
# BUSINESS_DB_DRIVER=dmAsync
# BUSINESS_DB_SERVICE_NAME=DM_CLUSTER
# BUSINESS_DM_SVC_PATH=C:\Windows\System32

API_HOST=0.0.0.0
API_PORT=8000
DEBUG=true

# 上海知天气小时雨量采集
ZTQ_RAINFALL_ENABLED=true
ZTQ_RAINFALL_DRY_INTERVAL_SECONDS=10800
ZTQ_RAINFALL_ACTIVE_INTERVAL_SECONDS=1800
ZTQ_RAINFALL_MIN_INTERVAL_SECONDS=300
ZTQ_RAINFALL_STALE_SECONDS=21600
# 默认站点：A5151 宝山大场上大附中，58362 宝山区级站
# ZTQ_RAINFALL_STATIONS='[{"station_id":"A5151","station_name":"宝山大场上大附中","role":"primary","longitude":121.39,"latitude":31.31},{"station_id":"58362","station_name":"宝山","role":"backup","longitude":121.4447222,"latitude":31.39083333}]'
```

## 系统特性

- **实时监测**: WebSocket 实时数据推送
- **数据可视化**: ECharts 图表展示
- **分级存储**: MySQL 分区表 + 自动归档
- **告警系统**: 多级别告警 + 自动检测
- **响应式设计**: 支持桌面和移动端
- **权限管理**: 基于角色的访问控制

## 技术栈

- **后端**: FastAPI + SQLAlchemy + MySQL
- **前端**: Vue 3 + Element Plus + ECharts
- **服务器**: Caddy + PHP-FPM
- **数据库**: MySQL 8.0
- **消息队列**: 可选集成 MQTT/Kafka

## 许可证

LGPL-3.0
