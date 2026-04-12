#!/bin/bash
# 一键启动 Docker 环境 (Linux/macOS)

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  校园水浸监测系统 - Docker 启动脚本${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: 未找到 Docker，请先安装 Docker${NC}"
    echo "安装指南: https://docs.docker.com/get-docker/"
    exit 1
fi

# 检查 Docker Compose
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif docker-compose version &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}错误: Docker Compose 未安装${NC}"
    exit 1
fi

echo -e "${GREEN}Docker 版本: $(docker version --format '{{.Server.Version}}')${NC}"
echo ""

# 检查 .env 文件
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo -e "${YELLOW}未找到 .env 文件，使用默认配置 .env.docker${NC}"
    cp "$PROJECT_DIR/.env.docker" "$PROJECT_DIR/.env"
    echo -e "${GREEN}已创建 .env 文件${NC}"
fi

HOST_HTTP_PORT="$(grep -E '^HOST_HTTP_PORT=' "$PROJECT_DIR/.env" | tail -n 1 | cut -d '=' -f 2-)"
HOST_HTTP_PORT="${HOST_HTTP_PORT:-80}"
if [ "$HOST_HTTP_PORT" = "80" ]; then
    SITE_URL="http://localhost"
else
    SITE_URL="http://localhost:$HOST_HTTP_PORT"
fi

# 创建日志目录
mkdir -p "$PROJECT_DIR/logs"

echo -e "${BLUE}正在构建并启动服务...${NC}"
echo ""

# 构建并启动
if $COMPOSE_CMD -f "$PROJECT_DIR/docker-compose.yml" up --build -d; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  所有服务已启动！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "访问地址:"
    echo "  • 主站点:      $SITE_URL"
    echo "  • API 文档:    http://localhost:8000/docs"
    echo "  • Webhook:     http://localhost:8080/webhook/sensor"
    echo ""
    echo "常用命令:"
    echo "  查看日志:    $COMPOSE_CMD logs -f"
    echo "  停止服务:    ./stop-docker.sh"
    echo "  重启服务:    $COMPOSE_CMD restart"
    if [ "$HOST_HTTP_PORT" != "80" ]; then
        echo ""
        echo -e "${YELLOW}当前主站点使用自定义端口 $HOST_HTTP_PORT。${NC}"
    fi
else
    echo -e "${RED}服务启动失败${NC}"
    exit 1
fi
