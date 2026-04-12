# DM8 Test Environment

本地 DM8 测试环境建议按独立测试实例维护，以下内容使用占位符示例：

- 实例目录：`D:\dmdata\YOUR_DB`
- 监听地址：`127.0.0.1:5236`
- 业务用户：`YOUR_APP_USER`
- 业务密码：`ChangeMe_123!`
- 当前启动方式：直接运行 `dmserver.exe D:\dmdata\YOUR_DB\dm.ini`

## Start

当前未注册 Windows 服务，重启后需手动启动：

```powershell
Start-Process -FilePath "D:\Program Files\dmdbms\bin\dmserver.exe" -ArgumentList "D:\dmdata\YOUR_DB\dm.ini"
```

确认端口监听：

```powershell
netstat -ano | Select-String ":5236"
```

确认数据库可连接：

```powershell
& "D:\Program Files\dmdbms\bin\DIsql.exe" 'YOUR_APP_USER/"ChangeMe_123!"@127.0.0.1:5236'
```

## Python Drivers

达梦 Python 驱动源码已随安装包提供：

- `D:\Program Files\dmdbms\drivers\python\dmPython`
- `D:\Program Files\dmdbms\drivers\python\dmAsync`
- `D:\Program Files\dmdbms\drivers\python\dmSQLAlchemy\dmSQLAlchemy2.0`

推荐安装顺序：

```powershell
$env:DM_HOME = "D:\Program Files\dmdbms"
.\backend\scripts\install_dm_drivers.ps1
```

如果需要手工执行：

```powershell
python -m pip install --user "D:\Program Files\dmdbms\drivers\python\dmPython"
python -m pip install --user "D:\Program Files\dmdbms\drivers\python\dmAsync"
python -m pip install --user "D:\Program Files\dmdbms\drivers\python\dmSQLAlchemy\dmSQLAlchemy2.0"
```

## Backend Config

后端建议优先使用结构化配置。

原因：
- 如果密码包含 `@` 等特殊字符，手写 `DATABASE_URL` 很容易因为未转义而解析错误。

结构化配置：

```env
DM_HOME=D:\Program Files\dmdbms
DB_DIALECT=dm
DB_DRIVER=dmAsync
DB_HOST=127.0.0.1
DB_PORT=5236
DB_NAME=YOUR_DB
DB_USER=YOUR_APP_USER
DB_PASSWORD=ChangeMe_123!
```

如果必须使用连接串，密码中的特殊字符必须编码：

```env
DATABASE_URL=dm+dmAsync://YOUR_APP_USER:ChangeMe_123%21@127.0.0.1:5236/YOUR_DB
```

## Notes

- 达梦脚本入口：`database/dm/init.sql`
- 测试环境引导脚本：`database/dm/bootstrap-test-env.sql`
- 本次实跑修复记录：`database/dm/repair-test-env.sql`
- 应用启动时默认不会替达梦自动建基础表；空库必须先执行 `database/dm/init.sql`
- 目前数据库侧 JOB 尚未迁移，维护任务仍建议由应用层触发。
