# 达梦数据库脚本目录

这个目录保留给达梦 V8 的初始化脚本和运维脚本。

当前状态：
- 仓库已经完成应用层数据库连接解耦，可通过 `DATABASE_URL` 或 `DB_DIALECT`/`DB_DRIVER` 切换方言入口。
- 后端结构化配置已支持达梦服务名模式，可通过 `DB_SERVICE_NAME` + `DM_SVC_PATH` 连接单位下发的高可用集群。
- 已提供 `init.sql` 首版，覆盖基础建表、索引和默认数据。
- 已提供 `20260523_weather_rainfall_split.sql`，用于把雨量实况、滚动预报和实况修正日志拆到独立表，并从旧 `rainfall_hourly` 回填当前值。
- 达梦默认不再走 ORM 自动建表；空库请先执行 `database/dm/init.sql`，否则 API 启动时会直接报错提示缺失基础表。
- `docker-compose.yml` 仍保留 MySQL + WordPress 默认拓扑，但后端已支持通过 `BACKEND_DB_*` 切换业务库，并通过 `BACKEND_CONTROL_DATABASE_URL` 把控制库持久化到 SQLite。
- 如果后端运行在 Linux 容器中，还需要额外制作带 DM 客户端和 Python 驱动的镜像；仓库现已提供 `backend/Dockerfile.dm` 模板以及 Windows / Linux 安装脚本。
- 仓库里的 `backend/达梦 Python 接口源码-20260401/python` 可直接作为 `dmPython` / `dmAsync` / `dmSQLAlchemy` 的源码来源；但它不包含完整 Linux 运行时，仍需要额外提供 `libdmdpi.so` 和头文件。
- `backend/达梦 PHP_PDO 接口源码-20260401/php_pdo` 是 PHP 扩展目录，当前架构下不用于 FastAPI backend。

后续需要补齐的内容：
- `maintenance.sql`：如果继续依赖数据库侧定时任务，需要补达梦版本的存储过程或 JOB。
- 驱动安装和自举脚本：仓库内已提供 `backend/scripts/install_dm_drivers.ps1` 和 `backend/scripts/install_dm_drivers.sh`。

建议连接串格式：
- `dm+dmPython://USER:PASSWORD@HOST:5236/DBNAME`
- 服务名模式：`dm+dmPython://USER:PASSWORD@DM_CLUSTER/DBNAME`

环境建议：
- 参考达梦官方《从 MySQL 移植到 DM》文档，MySQL 迁移场景建议评估 `CASE_SENSITIVE`、`COMPATIBLE_MODE=4`、`ORDER_BY_NULLS_FLAG=2` 等兼容参数。
- 如果通过迁移工具导对象，官方建议勾选“保持对象名大小写”。

迁移重点：
- `AUTO_INCREMENT` 改为达梦自增/标识列方案。
- `BOOLEAN`、`JSON`、`ENUM` 改为达梦可接受的数据类型。
- `ON DUPLICATE KEY UPDATE`、`DELIMITER`、`EVENT` 等 MySQL 语法需要重写。
