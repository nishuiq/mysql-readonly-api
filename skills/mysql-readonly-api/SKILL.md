---
name: mysql-readonly-api
description: "Inspect and query configured MySQL profiles through a local readonly REST API. Use when Codex needs to discover available database environments, list schemas, search tables, inspect DDL, run SELECT/WITH queries, count rows, or explain queries without direct MySQL access."
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

Inspect IDEA-style DDL:

```text
GET /profiles/<profile>/ddl?schema=<schema>&table=<table>
GET /profiles/<profile>/ddl?schema=<schema>&table=<table1>,<table2>
GET /profiles/<profile>/ddl?schema=<schema>&table=<table1>&table=<table2>
```

## Query data

Send raw SQL as the request body.

```text
POST /profiles/<profile>/query?offset=0&limit=500
Body: select * from schema.table
```

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
- Run only `SELECT` or `WITH` SQL and omit SQL comments.
- Keep `limit` at or below `5000`.
- Treat one request as operating on one profile; do not attempt cross-profile joins.
- Read database error text and revise invalid SQL before retrying.
