# 达梦数据库脚本目录

这个目录保留给达梦 V8 的初始化脚本和运维脚本。

当前状态：
- 仓库已经完成应用层数据库连接解耦，可通过 `DATABASE_URL` 或 `DB_DIALECT`/`DB_DRIVER` 切换方言入口。
- 已提供 `init.sql` 首版，覆盖基础建表、索引和默认数据。
- 达梦默认不再走 ORM 自动建表；空库请先执行 `database/dm/init.sql`，否则 API 启动时会直接报错提示缺失基础表。
- `docker-compose.yml` 目前仍然是 MySQL 部署拓扑，达梦部署需要单独的 compose 或宿主机安装方案。

后续需要补齐的内容：
- `maintenance.sql`：如果继续依赖数据库侧定时任务，需要补达梦版本的存储过程或 JOB。
- 驱动安装和自举脚本：仓库内已提供 `backend/scripts/install_dm_drivers.ps1`，后续可补充 shell 版本。

建议连接串格式：
- `dm+dmPython://USER:PASSWORD@HOST:5236/DBNAME`

环境建议：
- 参考达梦官方《从 MySQL 移植到 DM》文档，MySQL 迁移场景建议评估 `CASE_SENSITIVE`、`COMPATIBLE_MODE=4`、`ORDER_BY_NULLS_FLAG=2` 等兼容参数。
- 如果通过迁移工具导对象，官方建议勾选“保持对象名大小写”。

迁移重点：
- `AUTO_INCREMENT` 改为达梦自增/标识列方案。
- `BOOLEAN`、`JSON`、`ENUM` 改为达梦可接受的数据类型。
- `ON DUPLICATE KEY UPDATE`、`DELIMITER`、`EVENT` 等 MySQL 语法需要重写。
