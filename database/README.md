# Database Scripts

数据库脚本已经按方言拆分：

- `mysql/init.sql`
- `mysql/procedures.sql`
- `dm/init.sql`
- `dm/20260523_weather_rainfall_split.sql`
- `dm/DEPLOY.md`
- `dm/README.md`
- `../.env.dm.example`

当前约定：

- `mysql/` 仍是默认部署脚本。
- `dm/` 已提供首版 DM8 初始化脚本和测试环境说明，但应用层自动建表尚未作为达梦默认入口。
- 根目录下旧的 `init.sql`、`procedures.sql` 只保留为兼容入口，内容会提示迁移后的新位置。
