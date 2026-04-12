#!/usr/bin/env pwsh
# 一键启动 Docker 环境 (Windows)

$PROJECT_DIR = $PSScriptRoot

# 颜色输出函数
function Write-ColorOutput($ForegroundColor) {
    $fc = $host.UI.RawUI.ForegroundColor
    $host.UI.RawUI.ForegroundColor = $ForegroundColor
    if ($args) { Write-Output $args }
    $host.UI.RawUI.ForegroundColor = $fc
}

function Write-Success { Write-ColorOutput Green $args }
function Write-Warning { Write-ColorOutput Yellow $args }
function Write-Error { Write-ColorOutput Red $args }
function Write-Info { Write-ColorOutput Cyan $args }

Write-Info "========================================"
Write-Info "  校园水浸监测系统 - Docker 启动脚本"
Write-Info "========================================"
Write-Output ""

# 检查 Docker 是否安装
if (!(Get-Command "docker" -ErrorAction SilentlyContinue)) {
    Write-Error "错误: 未找到 Docker，请先安装 Docker Desktop"
    Write-Output "下载地址: https://www.docker.com/products/docker-desktop"
    exit 1
}

# 检查 Docker Compose 是否可用
$dockerComposeCmd = "docker compose"
try {
    Invoke-Expression "$dockerComposeCmd version" | Out-Null
} catch {
    $dockerComposeCmd = "docker-compose"
    try {
        Invoke-Expression "$dockerComposeCmd version" | Out-Null
    } catch {
        Write-Error "错误: Docker Compose 未安装"
        exit 1
    }
}

Write-Info "Docker 版本:"
docker version --format '{{.Server.Version}}'
Write-Output ""

# 检查 .env 文件是否存在
if (!(Test-Path "$PROJECT_DIR\.env")) {
    Write-Warning "未找到 .env 文件，使用默认配置 .env.docker"
    Copy-Item "$PROJECT_DIR\.env.docker" "$PROJECT_DIR\.env"
    Write-Success "已创建 .env 文件"
}

$envContent = Get-Content "$PROJECT_DIR\.env" -ErrorAction SilentlyContinue
$hostHttpPort = "80"
foreach ($line in $envContent) {
    if ($line -match '^\s*HOST_HTTP_PORT\s*=\s*(.+?)\s*$') {
        $hostHttpPort = $matches[1].Trim()
        break
    }
}

$siteUrl = if ($hostHttpPort -eq "80") { "http://localhost" } else { "http://localhost:$hostHttpPort" }

# 创建必要的目录
if (!(Test-Path "$PROJECT_DIR\logs")) {
    New-Item -ItemType Directory -Path "$PROJECT_DIR\logs" -Force | Out-Null
}

Write-Info "正在构建并启动服务..."
Write-Output ""

# 构建并启动服务
try {
    Invoke-Expression "$dockerComposeCmd -f '$PROJECT_DIR\docker-compose.yml' up --build -d"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Output ""
        Write-Success "========================================"
        Write-Success "  所有服务已启动！"
        Write-Success "========================================"
        Write-Output ""
        Write-Output "访问地址:"
        Write-Output "  • 主站点:      $siteUrl"
        Write-Output "  • API 文档:    http://localhost:8000/docs"
        Write-Output "  • Webhook:     http://localhost:8080/webhook/sensor"
        Write-Output ""
        Write-Output "查看日志:"
        Write-Output "  docker compose logs -f"
        Write-Output ""
        Write-Output "停止服务:"
        Write-Output "  .\stop-docker.ps1"
        if ($hostHttpPort -ne "80") {
            Write-Output ""
            Write-Warning "当前主站点使用自定义端口 $hostHttpPort。"
        }
    } else {
        Write-Error "服务启动失败"
    }
} catch {
    Write-Error "启动出错: $_"
}

Write-Output ""
Write-Output "按任意键继续..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
