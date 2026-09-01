# mysql-readonly-api

极简的多数据源 MySQL 只读 REST 服务。一个 Python 进程可以同时加载多个启用的 `profile`，调用方先发现
profile，再在每个数据库请求的 URL 中显式指定 profile，不需要记忆端口与数据库环境的对应关系。

所有接口返回纯文本，不使用 `data/message/code` 外壳。普通结果集第一行是字段名，后续是数据行，字段之间
使用 tab 分隔。包含原始 Tab、换行或反斜杠的大文本应使用 `/query?raw=true` 单值模式读取。

## 启动

安装依赖、创建本地配置并启动：

```powershell
uv sync
Copy-Item config.example.yaml config.yaml
uv run main.py
```

服务只监听 `server.port` 配置的一个端口。启动日志会列出当前已启用的 profile。

## 配置

| 文件 | 说明 |
|---|---|
| `config.yaml` | 本地运行配置，不提交到仓库 |
| `config.example.yaml` | 可复制使用的示例配置 |

配置示例：

```yaml
app:
  name: mysql-readonly-api
  sql_log: true

server:
  host: 127.0.0.1
  port: 8765
  reload: false

query:
  default_limit: 500
  max_limit: 5000
  timeout_ms: 15000

profiles:
  example-dev:
    enabled: true
    description: Example development database
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

  example-prod:
    enabled: false
    description: Example production read-only database
    mysql:
      host: 127.0.0.1
      port: 13306
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
```

配置职责：

- `server` 只配置当前 REST 服务的监听地址，一个进程只有一份。
- `profiles` 中的每一项代表一个 MySQL 数据源。
- `enabled: true` 的 profile 会建立独立的惰性连接池并通过 API 暴露。
- `description` 会显示在 `/profiles` 中，帮助调用方选择正确的数据库环境。
- profile 名只能包含小写字母、数字、`-` 和 `_`。
- 禁用或不存在的 profile 均返回 `404 Unknown profile`。

服务不配置默认 schema，SQL 中仍需使用 `schema.table` 明确表名。一个请求只会在 URL 指定的单个 profile
上执行，不能跨 profile 联表。

`query.default_limit` 是 `/query` 的默认返回行数；`query.max_limit` 限制单次最多返回的行数；
`query.timeout_ms` 会设置 MySQL `max_execution_time`。`offset` 默认固定为 `0`，需要翻页时通过请求参数传入。

`app.sql_log: true` 时，控制台会打印 SQL 和参数，但不会打印查询结果。

## 接口

| 接口 | 方法 | 说明 | 参数或请求体 |
|---|---|---|---|
| `/health` | `GET` | 检查 REST 服务是否启动 | 无 |
| `/profiles` | `GET` | 列出已启用的 profile 及其描述 | 无 |
| `/profiles/{profile}/schemas` | `GET` | 列出指定 MySQL 中的业务 schema | 无 |
| `/profiles/{profile}/tables` | `GET` | 搜索指定 schema 下的表 | `schema` 必填，`keyword` 可选 |
| `/profiles/{profile}/ddl` | `GET` | 查看一个或多个 Table/View 的 IDEA 风格 DDL | `schema`、`table` 必填；`table` 可重复或逗号分隔 |
| `/profiles/{profile}/query` | `POST` | 执行只读 `SELECT/WITH/SHOW` SQL | 原始 SQL 请求体；`offset`、`limit`、`raw` 可选 |
| `/profiles/{profile}/count` | `POST` | 统计查询结果行数 | 原始 `SELECT/WITH` SQL 请求体 |
| `/profiles/{profile}/explain` | `POST` | 查看查询执行计划 | 原始 `SELECT/WITH` SQL 请求体 |

`/profiles` 返回示例：

```text
name	description
example-dev	Example development database
example-prod	Example production read-only database
```

## 调用示例

先发现可用 profile：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8765/profiles"
```

查询 profile 中的 schema：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8765/profiles/example-dev/schemas"
```

执行查询：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/profiles/example-dev/query?limit=500" `
  -ContentType "text/plain" `
  -Body "select * from example_app.orders"
```

`/query` 也支持 `SHOW`：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/profiles/example-dev/query" `
  -ContentType "text/plain" `
  -Body "show create table example_app.orders"
```

读取包含 Tab、换行或反斜杠的单个原始字段：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/profiles/example-dev/query?raw=true" `
  -ContentType "text/plain" `
  -Body "select routine_definition from information_schema.routines where routine_schema = 'example_app' and routine_name = 'example'"
```

Raw 查询必须恰好返回一行一列。成功时第一行是列名，第一个 LF 后的全部内容是字段原值，不执行 CR、LF、
Tab 或反斜杠转换。空字符串返回 `200` 和空内容；SQL `NULL` 返回 `204`；没有结果行返回 `404`；多行或
多列返回 `400`。

`/ddl` 会区分 Table 和 View。View 源码可见时返回数据库的 `SHOW CREATE VIEW` 定义；源码不可见时返回
`/* missing source code */` 占位以及可见的列注释，不会再把 View 渲染成 Table。

普通 `SELECT/WITH` 查询仍受 `query.max_limit` 限制。需要读取超过 5000 行的完整结果时，先使用 `/count`，
再使用稳定 `ORDER BY` 和 `offset/limit` 分页。

## Codex Skill

项目内置 skill：

```text
skills/mysql-readonly-api
```

将该目录复制到 Codex skills 目录即可安装。Windows 通常为：

```text
C:\Users\<用户名>\.codex\skills\mysql-readonly-api
```

skill 会先调用 `/profiles` 发现数据源，根据 profile 名和描述选择环境，然后在后续每个请求中显式携带该
profile。描述无法消除歧义时，应先向用户确认，不能自行猜测生产或测试环境。

## 通过 SSH 访问远程 MySQL

如果 MySQL 只能通过 SSH 服务器访问，可以为每个远程数据源建立不同的本地转发端口：

```powershell
ssh -N -L 13306:<mysql_host>:<mysql_port> <ssh_user>@<ssh_host>
```

然后把对应 profile 的 MySQL 地址指向本地转发端口：

```yaml
profiles:
  example-prod:
    enabled: true
    description: Example production read-only database
    mysql:
      host: 127.0.0.1
      port: 13306
      # 其余配置省略
```

本地转发终端需要保持运行。这里的 `13306` 是 MySQL 隧道端口，不是 REST API 端口；所有 profile 仍通过
同一个 REST `server.port` 访问。

## License

MIT
