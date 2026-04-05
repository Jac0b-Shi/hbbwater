# 校园水浸监测系统

基于 Vue 3 + FastAPI + MySQL 的物联网水浸监测数据存储与可视化系统。

## 功能特性

- 📊 **实时数据可视化** - ECharts 图表展示水位和浸水状态
- 🔔 **智能告警** - 多渠道告警通知（企业微信 webhook）
- 📱 **响应式设计** - 支持桌面和移动设备
- 🌐 **RESTful API** - 完整的 API 文档（Swagger UI）
- 🔧 **多传感器支持** - 超声波水位 + 浸水传感器

## 快速开始

**环境要求**: Docker 20.10+

```bash
# Windows
.\start-docker.ps1

# Linux / macOS
./start-docker.sh
```

访问 http://localhost 即可使用。

详见 [DOCKER.md](DOCKER.md)

## 项目结构

```
.
├── backend/           # FastAPI 后端
│   ├── app/          # 应用代码
│   ├── Dockerfile    # Docker 配置
│   └── requirements.txt
├── frontend/         # Vue 3 前端
│   ├── src/          # 源代码
│   ├── Dockerfile
│   └── package.json
├── webhook_proxy/    # Webhook 代理服务
│   ├── webhook_proxy.py
│   └── Dockerfile
├── caddy/            # Caddy 反向代理配置
├── database/         # 数据库初始化脚本
├── docker-compose.yml    # Docker 编排配置
├── start-docker.sh       # Docker 启动脚本
└── docs/             # 项目文档
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3, Element Plus, ECharts, Vite |
| 后端 | FastAPI, SQLAlchemy, Pydantic |
| 数据库 | MySQL 8.0 |
| 代理 | Caddy 2 |
| 部署 | Docker, Docker Compose |

## API 文档

启动服务后访问：http://localhost:8000/docs

## 许可证

LGPL-3.0
