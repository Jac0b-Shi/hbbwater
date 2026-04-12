# 校园水浸监测数据存储与可视化系统

基于MySQL分级存储、Headscale安全组网、Vue+WordPress前后端分离的完整技术解决方案。

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
         │    ┌─────────────────────────────────┐   │
         └───►│       MySQL 8.0 数据库           │◄──┘
              │  - sensor_readings (热数据)      │
              │  - sensor_readings_archive (归档)│
              │  - sensor_summary_* (汇总)       │
              │  - alerts (告警)                 │
              └─────────────────────────────────┘
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

## 数据库架构

### 分级存储策略

- **热数据** (`sensor_readings`): 最近14天的原始数据，支持高频查询
- **归档数据** (`sensor_readings_archive`): 超过14天的历史数据
- **汇总数据** (`sensor_summary_hourly/daily`): 小时/日统计数据

### 自动维护

- 每小时自动归档过期数据
- 每小时自动计算小时汇总
- 每日自动计算日汇总
- 每10分钟检查离线传感器
- 每小时检查低电量告警

## 配置文件

### 后端环境变量 (.env)

```bash
DB_HOST=localhost
DB_PORT=3306
DB_NAME=flood_monitoring
DB_USER=flood_user
DB_PASSWORD=flood_monitoring_2025

API_HOST=0.0.0.0
API_PORT=8000
DEBUG=true
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
