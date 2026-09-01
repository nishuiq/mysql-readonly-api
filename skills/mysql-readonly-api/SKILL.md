---
name: mysql-readonly-api
description: "Inspect and query configured MySQL profiles through a local readonly REST API. Use when Codex needs to discover available database environments, inspect metadata or DDL, run SELECT/WITH/SHOW queries, count rows, or explain queries without direct MySQL access."
---

# MySQL Readonly API

Use the service at `http://127.0.0.1:8765` unless the user provides another base URL.

## Select a profile

Check the service, then discover enabled profiles:

```text
GET /health
GET /profiles
```

Expect `/profiles` as tab-separated text:

```text
name	description
example-dev	Example development database
example-prod	Example production read-only database
```

Use a profile explicitly named by the user. Otherwise, select one only when its name and description unambiguously match
the request. Ask the user when multiple profiles could match or when choosing between production and non-production is
unclear. Keep the selected profile in every subsequent database request; do not assume a server-side default or switch
state.

## Inspect metadata

List schemas:

```text
GET /profiles/<profile>/schemas
```

Search tables:

```text
GET /profiles/<profile>/tables?schema=<schema>&keyword=<keyword>
```

Inspect IDEA-style Table/View DDL:

```text
GET /profiles/<profile>/ddl?schema=<schema>&table=<table>
GET /profiles/<profile>/ddl?schema=<schema>&table=<table1>,<table2>
GET /profiles/<profile>/ddl?schema=<schema>&table=<table1>&table=<table2>
```

The DDL endpoint distinguishes tables from views. An unavailable view definition is shown as `missing source code`.

## Query data

Send raw `SELECT`, `WITH`, or `SHOW` SQL as the request body.

```text
POST /profiles/<profile>/query?offset=0&limit=500
Body: select * from schema.table
```

Use `SHOW` for database-provided definitions and metadata. Visibility follows the selected profile's database privileges.

For one large text value containing tabs, newlines, or backslashes, use raw mode:

```text
POST /profiles/<profile>/query?raw=true
Body: select routine_definition from information_schema.routines where ...
```

Raw mode requires one row and one column. The first line is the column name; everything after the first LF is the
unmodified value. SQL NULL returns 204, no row returns 404, and other result shapes return 400.

Count rows:

```text
POST /profiles/<profile>/count
Body: select * from schema.table
```

Explain a query:

```text
POST /profiles/<profile>/explain
Body: select * from schema.table
```

## Read results safely

Treat all responses as `text/plain`. Query results are tab-separated with the first row containing column names.

- Inspect `/schemas`, `/tables`, and `/ddl` before writing SQL when structure is unknown.
- Use explicit `schema.table` names; do not rely on a default schema.
- Count first and use a stable `ORDER BY` with `offset` pagination when a complete result can exceed `5000` rows.
- Use raw mode rather than ordinary TSV for definitions or other fields that may contain tabs or newlines.
- Treat `missing source code`, HTTP 204, and permission failures as unavailable definitions.
