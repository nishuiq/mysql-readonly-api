---
name: mysql-readonly-api
description: "Use when Codex needs to inspect or query a local readonly MySQL REST API: list schemas, search tables, inspect table DDL, run SELECT/WITH queries, or count query results."
---

# MySQL Readonly API

Use this service to read MySQL data through HTTP.

Default base URL:

```text
http://127.0.0.1:8765
```

If the user gives another host or port, use that instead.

## What It Does

- List schemas.
- Search tables in a schema.
- Inspect table DDL.
- Run readonly `SELECT` / `WITH` SQL.
- Count rows for a `SELECT` / `WITH` SQL.
- Explain a `SELECT` / `WITH` SQL.

## How To Use

Check service:

```text
GET /health
```

List schemas:

```text
GET /schemas
```

Search tables:

```text
GET /tables?schema=<schema>&keyword=<keyword>
```

Inspect IDEA-style DDL:

```text
GET /ddl?schema=<schema>&table=<table>
GET /ddl?schema=<schema>&table=<table1>,<table2>
GET /ddl?schema=<schema>&table=<table1>&table=<table2>
```

Query data:

```text
POST /query?offset=0&limit=500
Body: select * from schema.table
```

Count rows:

```text
POST /count
Body: select * from schema.table
```

Explain query:

```text
POST /explain
Body: select * from schema.table
```

## Results

All responses are `text/plain`.

Query results are tab-separated text:

```text
id	name
1	Alice
2	Bob
```

SQL must use explicit table names:

```sql
select * from biz_order.order_main
```

Do not rely on a default schema.

## Usage Rules

- Use `/schemas`, `/tables`, and `/ddl` before writing SQL when table structure is unknown.
- Use `/query` for sample rows and analysis queries.
- Use `/count` when the user asks for quantity or total rows.
- Use `/explain` when the user asks about query plans or index usage.
- Only run read-only query operations. Any non-query operation is invalid.
- Do not include SQL comments.
- Keep `limit` at or below `5000`.
- If the API returns a SQL error, read the database error text and revise the SQL.
