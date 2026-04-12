# Docker 部署指南

使用 Docker 可以实现真正的跨平台部署，一次构建，到处运行！

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                         Caddy (80, 8000)                    │
│                    ┌──────────────────┐                     │
│  浏览器 ────────▶ │   反向代理/网关    │                     │
│                   └────────┬─────────┘                     │
└────────────────────────────┼───────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   Frontend      │  │     Backend     │  │  Webhook Proxy  │
│   (Vue/Caddy)   │  │   (FastAPI)     │  │    (Python)     │
│      :80        │  │     :8000       │  │     :8080       │
└─────────────────┘  └─────────────────┘  └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   MySQL 8.0     │
                    │     :3306       │
                    └─────────────────┘
```

## 环境要求

- **Docker** 20.10+
- **Docker Compose** 2.0+
- 至少 **2GB** 可用内存
- 至少 **5GB** 可用磁盘空间

## 快速开始

### 1. 安装 Docker

- **Windows/macOS**: 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop)
- **Linux**: 
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER
  ```

### 2. 启动服务

#### 方式一：使用脚本（推荐）

```bash
# Windows (PowerShell)
.\start-docker.ps1

# Windows (CMD)
start-docker.bat

# Linux / macOS
./start-docker.sh
```

#### 方式二：使用 Docker Compose 命令

```bash
# 复制环境配置
cp .env.docker .env

# 启动所有服务
docker compose up --build -d

# 查看日志
docker compose logs -f

# 停止服务
docker compose down
```

### 3. 访问系统

| 地址 | 说明 |
|------|------|
| http://localhost | 主站点 (Vue 前端) |
| http://localhost:8000/docs | API 文档 (Swagger UI) |
| http://localhost:8000 | FastAPI 后端直连 |
| http://localhost:8080/webhook/sensor | Webhook 接收端点 |

如果 `http://localhost` 被宿主机上的其他服务占用，可在 `.env` 中设置：

```env
HOST_HTTP_PORT=8081
```

然后改用 `http://localhost:8081` 访问主站点。

## PhpStorm 一键启动

1. 打开 PhpStorm
2. 点击顶部运行配置下拉菜单
3. 选择 **"⭐ Docker Start & Open Website"**
4. 点击运行按钮 ▶️

或使用单独的配置：
- `Docker Compose Up` - 启动所有容器
- `Docker Compose Down` - 停止所有容器

## 常用命令

```bash
# 查看运行状态
docker compose ps

# 查看日志（所有服务）
docker compose logs -f

# 查看特定服务日志
docker compose logs -f backend
docker compose logs -f mysql

# 重启服务
docker compose restart backend

# 进入容器内部
docker compose exec mysql mysql -uflood_user -p

# 重建并启动
docker compose up --build -d

# 完全清理（包括数据卷）
docker compose down -v
```

## 配置说明

### 环境变量

编辑 `.env` 文件修改配置：

```env
# 数据库
MYSQL_ROOT_PASSWORD=root_password_2025
DB_NAME=flood_monitoring
DB_USER=flood_user
DB_PASSWORD=flood_monitoring_2025

# API
DEBUG=false
SECRET_KEY=your-secret-key-change-this-in-production

# 主站点端口
HOST_HTTP_PORT=80

# Webhook（企业微信）
WEBHOOK_KEY=your_wechat_webhook_key
```

### 数据持久化

MySQL 数据保存在 Docker Volume 中：

```bash
# 查看数据卷
docker volume ls

# 备份数据库
docker compose exec mysql mysqldump -uroot -p flood_monitoring > backup.sql

# 恢复数据库
docker compose exec -i mysql mysql -uroot -p flood_monitoring < backup.sql
```

## 服务详情

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| mysql | mysql:8.0 | 3306 | MySQL 数据库 |
| backend | 本地构建 | 8000 | FastAPI 后端 |
| frontend | 本地构建 | 80 | Vue 前端 |
| webhook-proxy | 本地构建 | 8080/tcp+udp | Webhook 代理 |
| caddy | 本地构建 | 80, 8000 | 反向代理 |

## 开发模式

仅启动数据库用于本地开发调试：

```bash
# 仅启动数据库
docker compose up -d mysql
```

数据库将在 `localhost:3306` 可用，可连接进行开发和测试。

## 生产部署

### 使用 Docker Swarm

```bash
# 初始化 Swarm
docker swarm init

# 部署
docker stack deploy -c docker-compose.yml flood-monitoring

# 查看服务
docker stack ps flood-monitoring
```

### 使用 Docker Compose + Traefik

生产环境建议使用 Traefik 替代 Caddy，配合 Let's Encrypt 自动 HTTPS：

```yaml
# docker-compose.prod.yml
services:
  traefik:
    image: traefik:v3.0
    command:
      - "--api.insecure=true"
      - "--providers.docker=true"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.email=your@email.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./letsencrypt:/letsencrypt
```

## 故障排查

### 端口被占用

```bash
# 检查端口占用
netstat -ano | findstr :80

# 或改用其他主站点端口
# 编辑 .env，把 HOST_HTTP_PORT 改成 8081 等未占用端口
```

如果你打开 `http://localhost` 看到的是 `Caddy works!`，通常表示宿主机上已经有另一个 Caddy 或其他 Web 服务占用了 80 端口，而不是本项目本身有问题。

### 数据库连接失败

```bash
# 查看 MySQL 日志
docker compose logs mysql

# 检查数据库是否就绪
docker compose exec mysql mysqladmin ping -uroot -p
```

### 容器启动失败

```bash
# 查看详细日志
docker compose logs --tail=100 [service-name]

# 重建容器
docker compose up -d --build --force-recreate [service-name]
```

### 清理重建

```bash
# 停止并删除所有容器和数据
docker compose down -v

# 删除所有镜像
docker compose down --rmi all

# 完全清理后重建
docker compose up --build -d
```

## 跨平台说明

本 Docker 配置支持：

- ✅ Windows (Docker Desktop)
- ✅ macOS (Docker Desktop)
- ✅ Linux (Docker Engine)
- ✅ ARM64 (Apple Silicon, Raspberry Pi)

所有镜像均使用官方多架构支持的基础镜像。
