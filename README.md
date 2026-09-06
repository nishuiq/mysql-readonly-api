# mysql-readonly-api

供 AI skill 调用的轻量 MySQL 只读 REST API。一个服务支持多个 profile，使用 MySQL 5.7（GA 版本）或 8.x。
默认返回紧凑文本，需要准确区分字段边界、NULL 或读取源码时用 `format=json`。

## 启动与配置

需要 Python 3.13+ 和 uv：

```powershell
uv sync
Copy-Item config.example.yaml config.yaml
# 编辑 config.yaml，填写数据库连接并启用 profile
uv run main.py
```

也可用 `uv run uvicorn app.factory:create_app --factory --host 127.0.0.1 --port 8765`。
本地 `config.yaml` 不提交。示例配置只列常用项，省略的值使用以下默认值：

| 配置 | 默认值 / 说明 |
|---|---|
| `app.name` / `app.sql_log` | `mysql-readonly-api` / `false`；开启 SQL 日志会记录 SQL 和绑定参数 |
| `server.host` / `port` / `reload` | `127.0.0.1` / `8765` / `false` |
| `query.default_limit` / `max_limit` | `500` / `5000`，默认值不能超过上限 |
| `query.timeout_ms` | `15000`，设置 MySQL `max_execution_time` |
| `profiles.<name>.enabled` | `false`；名称用小写字母、数字、`-`、`_`，首字符为字母或数字 |
| `profiles.<name>.description` | 必填，用于选择环境 |
| `mysql.host` / `username` / `password` | 每个 profile 必填；密码须为字符串，可为空 |
| `mysql.port` | `3306` |
| `mysql.character_encoding` / `use_unicode` | `utf8mb4` / `true` |
| `mysql.use_ssl` / `ssl_ca` | `true` / `null`；启用 TLS 并校验证书、主机名，可指定 CA 文件 |
| `mysql.server_timezone` | `+08:00`；空字符串保留服务端时区 |
| `mysql.connect_timeout` / `read_timeout` / `write_timeout` | `10` / `30` / `30` 秒 |
| `mysql.pool.size` / `max_overflow` | `5` / `10` |
| `mysql.pool.timeout` / `recycle` / `pre_ping` | `30` 秒 / `3600` 秒 / `true` |

布尔值使用 YAML `true/false`，数字使用整数。每个启用的 profile 有独立的惰性连接池。
URL 中必须指定 profile，SQL 中使用 `schema.table`，没有默认 schema，也不能跨 profile 联表。
未知或禁用的 profile 返回 404。

服务默认仅监听本机，**不提供 HTTP 身份认证**。数据库账号应仅具有任务需要的读取权限。
每个新物理连接设置 `SET SESSION TRANSACTION READ ONLY`，并在请求结束时回滚事务。
SQL 词法检查和只读会话用于减少误操作；它们不是任意 SQL 的完整安全沙箱，也不取代账号权限。
例如 MySQL 允许只读事务修改临时表，存储函数的能力也取决于数据库端定义和授权。

TLS 开启时不再允许静默降级到明文；自签名证书需配置 CA，主机名必须匹配证书。
通过 SSH 转发时仍需考虑证书主机名；只有明确使用非 TLS 连接时才设置 `use_ssl: false`。
SSH 端口是 MySQL 端口，与 REST 监听端口无关。

`max_execution_time` 主要限制只读 SELECT，不覆盖所有 SHOW、元数据工作或存储程序；
socket 超时是网络读写超时，不保证数据库任务在同一时刻取消。行数限制也不是字节限制，
单个大字段仍会完整返回，请按需选择列或在 SQL 中主动截取。

## 接口与格式

| 方法 / 路径 | 参数或请求体 |
|---|---|
| `GET /profiles` | 已启用的 profile 名称、描述 |
| `GET /profiles/{profile}/schemas` | 业务 schema，支持 `limit` |
| `GET /profiles/{profile}/tables` | `schema` 必填，`keyword` 可选，支持 `limit`；返回名称、类型、注释、估计行数 |
| `GET /profiles/{profile}/ddl` | `schema`、`table` 必填；`table` 可重复或逗号分隔 |
| `POST /profiles/{profile}/query` | UTF-8 `text/plain` SQL；支持 `limit`、`offset` |
| `POST /profiles/{profile}/count` | UTF-8 `text/plain` SELECT/WITH，统计该 SQL 的结果行数 |
| `POST /profiles/{profile}/explain` | UTF-8 `text/plain` SELECT/WITH，支持 `limit` |

除 `/ddl` 固定返回文本外，其余接口支持 `format=text|json`，默认 `text`。

文本第一行是列名，字段用 tab、记录用 LF 分隔。**不改写字符串中的 CR、LF、tab、反斜杠**，
不把零日期转换成 NULL。这是供阅读的文本展示，不是可以无歧义解析的转义 TSV：
SQL NULL 与字符串 `"NULL"` 均显示为 `NULL`，字段自身也可能包含换行或 tab。
存在更多结果时，文本前置一行 `[truncated]`，下一行立即是列名，不插入空行、不附带分页参数：

```text
[truncated]
id	name
1	Alice
2	Bob
```

JSON 只写一次列名，以二维数组存储行，原生区分 `null`、字符串和字段边界：

```json
{"columns":["id","body"],"rows":[[1,"line1\nline2"],[2,null]],"truncated":false}
```

JSON 的 `\n` 是标准 JSON 编码，解码后恢复实际换行；数据库里的字面量反斜杠+n 则编码为 `\\n`。
两种格式均支持任意行列数。空结果返回 200（文本只有表头，JSON 为 `rows:[]`），SQL NULL 也返回 200。

| 数据类型 | 文本 | JSON |
|---|---|---|
| 字符串、整数、浮点数 | 驱动值的文本表示 | 字符串、number |
| DECIMAL | 保留精度和小数位 | 字符串，避免转 float 丢失精度 |
| DATE / DATETIME / TIMESTAMP | 日期时间文本 | 同样的字符串；TIMESTAMP 按会话时区返回 |
| TIME | `[-]HH:MM:SS[.ffffff]`，可超过 24 小时 | 同样的字符串 |
| 二进制（包括 BIT） | `0x...` 十六进制 | `{"hex":"..."}` |
| SQL NULL | `NULL` | `null` |

JSON 保留值和行列边界，但不是完整的 MySQL 类型协议：日期/DECIMAL 仍是字符串，
MySQL JSON 字段也保留驱动返回的字符串，需要时再解码；不自动展开字段内容。
使用 JavaScript 处理大整数时须注意 number 精度；可在 SQL 中 CAST 为 CHAR。
`use_unicode: false` 会使字符字段按驱动返回的 bytes 使用二进制约定。

## 查询、分页与原生定义

`/query` 接受单条 SELECT/WITH/SHOW，可带普通注释和末尾分号。
允许字符串里的关键字、分号及 `REPLACE()`；支持 `@@` 系统变量读取。
拒绝写操作、CALL/SET、用户变量赋值与读取、锁定读、文件/等待/锁函数、可执行注释和优化器 hint。
词法边界遵循连接的 `sql_mode`，不为通过校验而改写用户 SQL。具体语法由 MySQL 决定，5.7 不支持 WITH/CTE。

SELECT/WITH 保留外层分页：

```sql
SELECT *
FROM (
  -- 用户 SQL
) AS _codex_query
LIMIT <limit + 1> OFFSET <offset>
```

只返回前 `limit` 行，第 `limit + 1` 行用于判断截断，不预先 COUNT。
外层分页作用于原 SQL 的结果，内层 LIMIT 保持有效；同名结果列会触发 MySQL 派生表限制，
此时错误提示要求为结果列设置不同别名。此路径不会先取回全部 SELECT 结果。

外层派生表不能普遍保证保留内层 ORDER BY 的顺序。要求严格排序时，
在自己的 SQL 中使用唯一稳定的 ORDER BY，并写好 LIMIT/OFFSET 或基于键的翻页条件，
API offset 保持 0、API limit 至少等于 SQL 页大小。此时截断标志只反映**提交的 SQL 结果**，
不会越过 SQL 自己的 LIMIT 探测底层表；多次请求不共享快照，数据变化时 offset 分页仍可能重复或遗漏。
仅需常规浏览时可使用 API limit/offset；需要总数再调用 count。

SHOW 直接执行，返回最多 `limit` 行并判断截断，不套 SELECT，也不向原句追加 LIMIT。
API offset 非 0 返回 422；SHOW 自带的语法由 MySQL 处理。
SHOW 使用驱动缓冲结果，返回行数受限不意味着服务端只产生或驱动只接收这些行。
大量、可分页元数据应查询 `information_schema`；schemas/tables 的结果截断时也可改用该方式。

```powershell
$base = "http://127.0.0.1:8765"
Invoke-RestMethod "$base/profiles"
$sql = "SELECT id, name FROM example_app.orders ORDER BY id LIMIT 20"
Invoke-RestMethod -Method Post -Uri "$base/profiles/example-dev/query?limit=20" -ContentType "text/plain; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($sql))

$sql = "SHOW CREATE PROCEDURE example_app.example"
$result = Invoke-RestMethod -Method Post -Uri "$base/profiles/example-dev/query?format=json" -ContentType "text/plain; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($sql))
$result.rows
```

`/ddl` 保留紧凑对齐风格，展示字段、默认值、生成列、主键/索引、外键和表属性；
8.x 按版本补充表达式索引、索引可见性和实际存储的 CHECK 约束，5.7 不查询这些专属字段。
它是**结构摘要**，不用于备份或迁移：普通整数显示宽度会省略（ZEROFILL 保留），
不区分显式 DEFAULT NULL 和未指定默认值，不完整重建分区、表空间及全部引擎选项。
额外表选项存在时给出简短提示。DDL 字符串引用遵循当前会话 sql_mode。
含逗号的对象名使用反引号包裹后作为 table 参数传入。

需要完整原生定义时，直接 query `SHOW CREATE TABLE/VIEW/PROCEDURE/FUNCTION/EVENT`；
多行源码推荐 JSON。View 源码可见时直接使用原生 SHOW CREATE VIEW，
仅权限不足时返回 `missing source code` 占位，其他数据库错误正常上报。

元数据可见性取决于账号授权。查询通常需要 SELECT，视图源码需要 SHOW VIEW；
过程/函数、事件源码按 MySQL 版本和账号身份处理。5.7 没有 SHOW_ROUTINE，
8.0.20+ 才提供此权限。不建议为了读取源码给 AI 账号授予宽泛的管理/写入权限。
NULL 源码表示当前账号不可见，不能当成空定义。

## 错误、skill 与验证

错误始终是纯文本，即使请求 `format=json`；先检查 HTTP 状态再解析 JSON。
SQL 错误保留 MySQL errno 和驱动消息，不附加 SQLAlchemy 的 SQL/参数堆栈。
连接错误隐藏账号、地址等细节；服务器日志默认也不打印完整 SQL 异常。

| HTTP | 含义 |
|---|---|
| 400 | SQL 校验、语法、重复列名等，可根据提示修改 SQL |
| 403 | 权限不足或违反只读事务 |
| 404 | 未知/禁用 profile，或对象不存在/不可见 |
| 422 | 参数错误，指出具体参数；包括 SHOW offset、旧 raw 参数 |
| 503 | 连接、认证、TLS、连接池问题 |
| 504 | 查询超时或被中断 |
| 500 | 内部异常 |

将 `skills/mysql-readonly-api` 目录复制到本地 skills 目录即可使用（通常 `~/.codex/skills`）。
Skill 负责调用方法；本 README 负责服务配置与实现边界。
已知 profile 可以直接使用，无需重复发现；count 和元数据遍历都按任务需要调用。

升级旧配置/调用方：删除 `zero_datetime_behavior`；`raw` 改为 `format=json` 或 `format=text`；
删除 health 探活流程；外部 uvicorn 启动命令改用 factory；核对真实 TLS 配置。
不会自动改动未提交的本地配置。

```powershell
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
```

集成测试默认跳过。指定**专用测试实例**的 `MYSQL_TEST_PORT` 后运行同一命令；
可另设 `MYSQL_TEST_HOST`（默认 127.0.0.1）、`MYSQL_TEST_USER`（root）、`MYSQL_TEST_PASSWORD`（空）。
测试使用无 TLS 本地连接，在随机命名的 `readonly_api_test_*` schema 内创建表、视图、过程、事件，
测试后清理；账号需有这些操作权限。不会读取 config.yaml 或使用业务 profile。
分别在 5.7 和 8.x 执行可覆盖真实驱动与版本差异。
实例配置了可信 TLS 证书时，可另设 `MYSQL_TEST_SSL_CA` 指向 CA 文件，启用真实 TLS 验证。

本地临时测试环境、下载包和日志统一放在项目 `temp/` 下，该目录已被 Git 忽略。
MySQL ZIP 包、解压程序、测试数据和证书可集中放在 `temp/mysql-integration/`，测试结束后关闭实例。

## License

MIT
