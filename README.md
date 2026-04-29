# mysql-readonly-api

极简 MySQL 只读 REST 服务。所有接口只返回 `text/plain`，不返回 JSON，不套 `data/message/code` 这类外壳。
结果集文本格式：第一行是字段名，后续是数据行，字段之间用 tab 分隔。

## 启动

使用 `uv`：

```powershell
uv sync
uv run main.py
```

使用 `pip`：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python main.py
```

## 配置

| 文件 | 说明 |
|---|---|
| `config.yaml` | 默认配置文件 |
| `config.example.yaml` | 示例配置，不会被运行时自动读取 |

运行前需要创建并填写 `config.yaml`。

MySQL 配置示例：

```yaml
app:
  name: mysql-readonly-api
  sql_log: true

server:
  host: 127.0.0.1
  port: 8765
  reload: false

mysql:
  host: 127.0.0.1
  port: 3306
  username: readonly
  password: password
  use_unicode: true
  character_encoding: utf8
  zero_datetime_behavior: convert_to_null
  use_ssl: true
  server_timezone: "+08:00"
  pool:
    size: 5
    max_overflow: 10
    timeout: 30
    recycle: 3600
    pre_ping: true

query:
  default_offset: 0
  default_limit: 500
  max_limit: 5000
  timeout_ms: 15000
```

不配置默认 schema；查询时仍然需要显式写 `schema.table`。

`app.sql_log: true` 时会在控制台打印 SQL 执行语句和参数，不打印查询结果。

`query.max_limit` 控制 `/query` 单次最多返回多少行，默认 5000 行；`query.timeout_ms` 会设置 MySQL
`max_execution_time`，控制每个 SELECT 查询最多执行多少毫秒。

## 接口

| 接口 | 方法 | 能干什么 | 参数 | 请求体 | 返回 |
|---|---|---|---|---|---|
| `/health` | `GET` | 检查服务是否启动 | 无 | 无 | `OK` |
| `/schemas` | `GET` | 查看当前 MySQL 里有哪些业务 schema | 无 | 无 | schema 列表文本 |
| `/tables` | `GET` | 在指定 schema 下搜索表，适合表很多时按关键字找表 | `schema` 必填，`keyword` 可选 | 无 | 表名、注释、估算行数文本 |
| `/ddl` | `GET` | 查看一个或多个表的 IDEA 风格 DDL，包含字段、主键、唯一约束、普通索引 | `schema` 必填，`table` 必填；多个表可重复传 `table` 或用逗号分隔 | 无 | DDL 纯文本 |
| `/query` | `POST` | 执行 `SELECT/WITH` SQL，表名需要显式写成 `schema.table`，服务会在 SQL 外层包裹 `LIMIT/OFFSET`，默认返回 500 行，默认最大不超过 5000 行 | `offset` 可选默认 `0`，`limit` 可选默认 `500` | 原始 SQL 文本 | 查询结果文本 |
| `/count` | `POST` | 统计一条 `SELECT/WITH` 查询会返回多少行，表名需要显式写成 `schema.table` | 无 | 原始 `SELECT/WITH` SQL 文本 | count 结果文本 |
| `/explain` | `POST` | 查看一条 `SELECT/WITH` 查询的执行计划 | 无 | 原始 `SELECT/WITH` SQL 文本 | explain 结果文本 |

## 示例

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/query" `
  -ContentType "text/plain" `
  -Body "select * from biz_order.order_main"
```

## Codex Skill

项目内置 skill：

```text
skills/mysql-readonly-api
```

给同事使用时，将该目录复制到他的 Codex skills 目录：

```text
~/.codex/skills/mysql-readonly-api
```

Windows 通常是：

```text
C:\Users\<用户名>\.codex\skills\mysql-readonly-api
```
