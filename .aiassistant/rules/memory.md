---
apply: 始终
---

# hbbwater 项目记忆

## 项目定位

- 这是一个校园水浸监测系统，面向传感器数据接入、存储、告警和可视化。
- 当前主技术组合是 Vue 3 前端 + FastAPI 后端 + MySQL 8.0 + Caddy 反向代理。
- 项目包含独立的 `webhook_proxy` 服务，用于接收设备侧 HTTP/UDP 上报并转发。
- 项目还包含 WordPress 服务，当前主要承担邮件能力和部分管理侧集成，而不是核心业务 API。

## 部署与运行

- 根目录使用 `docker-compose.yml` 编排，核心服务有 `mysql`、`backend`、`webhook-proxy`、`frontend`、`wordpress`、`caddy`。
- 默认访问入口是 `http://localhost`，FastAPI 文档在 `http://localhost:8000/docs`。
- Windows 启动脚本是 `start-docker.ps1`，停止脚本是 `stop-docker.ps1`。
- 默认数据库名是 `flood_monitoring`，默认业务用户是 `flood_user`。

## 仓库与协作约定

- 远端仓库是 `https://gitee.com/Jac0b_Shi/hbbwater.git`。
- 当前远端使用 `main` 和 `develop` 分支。
- `main` 是稳定集成分支。
- `develop` 是默认开发分支，后续功能修改和日常开发应优先在 `develop` 进行。
- 只有在用户完成测试并确认没问题后，才应发起 PR 将 `develop` 合并进 `main`。
- 仓库已提供 Gitee 模板文件：
  - `.gitee/ISSUE_TEMPLATE.zh-CN.md`
  - `.gitee/PULL_REQUEST_TEMPLATE.zh-CN.md`
- 后续处理仓库协作配置时，应优先沿用 `.gitee/` 下的中文模板命名与路径。

## 后端事实

- FastAPI 主入口是 `backend/app/main.py`。
- API 路由统一挂载在 `/api` 前缀下，主要模块是：
  - `sensors`
  - `alerts`
  - `dashboard`
  - `config`
- 健康检查接口是 `/health`。
- 传感器数据接收主入口是 `POST /api/sensors/data`。
- 基于 token 的 webhook 数据接收入口是 `POST /api/sensors/webhook/{token}`。
- 仪表盘统计入口是 `GET /api/dashboard/stats`。
- 系统配置和通知配置分别位于 `GET/POST /api/config/system` 与 `GET/POST /api/config/notification`。

## 传感器与业务模型

- 支持两类传感器：`ultrasonic`（超声波水位）和 `immersion`（浸水检测）。
- `sensors` 表保存传感器配置、告警阈值、上报间隔、是否启用、上报方式和 webhook token。
- `sensor_readings` 保存热数据，默认保留 14 天。
- `sensor_readings_archive` 保存归档历史数据。
- `sensor_summary_hourly` 和 `sensor_summary_daily` 保存汇总统计。
- `alerts` 表保存告警记录。
- `system_config` 表保存保留期、离线阈值、告警冷却等系统配置。

## 当前可确认的行为约束

- 传感器创建时，如果 `report_method` 是 `webhook`、`mqtt` 或 `coap`，后端会自动生成 `webhook_token`。
- 传感器离线判定默认按 60 分钟阈值计算。
- 告警冷却默认值是 30 分钟，热数据保留默认值是 14 天。
- 通知配置支持邮件和 webhook。
- 邮件优先通过 WordPress 暴露的 API 发送，失败时再尝试直接 SMTP。

## Webhook 代理事实

- `webhook_proxy/webhook_proxy.py` 同时监听 TCP 和 UDP 的 8080 端口。
- TCP 模式用于转发 HTTP webhook 请求。
- UDP 模式用于接收 BC260 二进制载荷，并可转发到企业微信 webhook。
- 代理优先使用环境变量 `WEBHOOK_KEY`。

## 维护时的注意点

- 优先相信当前代码和 `docker-compose.yml`，不要默认相信 `docs/README.md` 中较早的架构描述。
- 当前项目不是 git 工作区，不能依赖 `git status` 或提交历史判断变更。
- 写项目说明或后续记忆时，应避免把截图、临时测试产物或推测性架构信息当成事实。
- 涉及这个项目的后续 git 提交，默认要求使用用户的 GPG 签名。
- 当前项目许可证是 `LGPL-3.0`，对应文本位于仓库根目录 `LICENSE`。

## 当前环境可直接使用的命令行工具

- 用户当前通过 Scoop 安装并可直接调用以下工具：`7zip`、`bat`、`bottom`、`delta`、`duf`、`dust`、`eza`、`fd`、`fzf`、`gitui`、`glow`、`jq`、`procs`、`ripgrep`、`sd`、`tldr`、`watchexec`、`xh`、`yazi`、`zoxide`。
- 在后续终端协作中，若任务适配，应优先直接使用这些工具，而不是退回更低效或更冗长的替代命令。
- 其中搜索文件优先使用 `fd`，搜索文本优先使用 `ripgrep`/`rg`，查看文件优先使用 `bat`，列目录优先使用 `eza`，处理 JSON 优先使用 `jq`。
- 涉及 HTTP 接口调试时可优先使用 `xh`；涉及目录跳转可考虑 `zoxide`；涉及交互筛选可考虑 `fzf`；涉及监控和进程观察可使用 `bottom` 与 `procs`。

