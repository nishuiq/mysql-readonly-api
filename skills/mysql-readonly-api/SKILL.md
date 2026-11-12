---
name: mysql-readonly-api
description: "Inspect MySQL schemas and object definitions or run readonly SQL through a local REST API with named database profiles."
---

# MySQL Readonly API

Base URL: `http://127.0.0.1:8765`, unless the user specifies another.

Reuse the established profile; otherwise call `GET /profiles` and select by name/description. Ask if the target is ambiguous.

Qualify SQL object names as `schema.name`; there is no default schema.

## Requests

| Request | Parameters / body | Result |
|---|---|---|
| `GET /profiles` | — | Enabled profiles |
| `GET /profiles/<profile>/schemas` | — | Visible business schemas |
| `GET /profiles/<profile>/tables` | `schema`; optional `keyword` | Tables/views with estimated row counts |
| `GET /profiles/<profile>/ddl` | `schema`, `table` (repeatable) | Compact structure |
| `POST /profiles/<profile>/query` | SELECT/WITH/SHOW/EXPLAIN | Rows, count or execution plan |

Send POST SQL directly as UTF-8 `text/plain`. URL-encode query parameters.

`query`, `schemas` and `tables` accept `limit`: a positive integer defaulting to the configured `query.limit`, which is also the hard cap and cannot exceed 5000. Query `offset` is nonnegative and defaults to 0.

## Results

`/profiles/<profile>/ddl` is plain text. For other endpoints, prefer TSV for browsing and ordinary queries: omit `format` for the default or explicitly use `format=tsv`.

Use `format=json` for programmatic row/field processing, verbatim source extraction, or distinguishing SQL NULL from the string `"NULL"`.

- TSV has a header and tab-separated fields; strings retain tabs, CR/LF and backslashes, so field boundaries are not reliably recoverable. SQL NULL and `"NULL"` both display as `NULL`.
- JSON: `{"columns":["a","b"],"rows":[[1,null]],"truncated":false}`.
- Decimal/date/time values are strings; TIME can be negative or exceed 24 hours. Binary values are `{"hex":"..."}` in JSON and `0x...` in text.
- Truncation: `[truncated]` on a line immediately before the TSV header, or JSON `truncated:true`. Empty results succeed with a header only or `rows:[]`.

## Query rules

Send one statement per request without SQL comments or a statement semicolon; these characters remain valid inside strings and quoted identifiers. `@@` reads are allowed; user variables, locking reads, file/wait/lock functions and EXPLAIN ANALYZE are rejected. MySQL 5.7 has no CTE support.

- The outermost SQL LIMIT row count must not exceed 5000, including the SELECT inside EXPLAIN; inner LIMITs and SQL offsets are not subject to that check.
- SELECT/WITH without an outer LIMIT receives an appended LIMIT/OFFSET. SELECT/WITH with an existing outer LIMIT, SHOW and EXPLAIN execute unchanged. API limit and offset apply to the returned rows; for EXPLAIN they apply to plan rows, not the explained SELECT.
- For counts or plans, send `SELECT COUNT(*) FROM schema.table` or `EXPLAIN SELECT ...` to `/query`. Count only when a total is needed; it may be expensive.
- Use a unique ORDER BY for stable ordering and prefer keyset predicates for deep paging. Requests do not share a snapshot.
- Truncation describes the submitted SQL result after API offset; SQL's own LIMIT can end the result before the underlying table is exhausted. Large offsets can require substantial database work and data transfer.

## Definitions

For native definitions, use `SHOW CREATE TABLE schema.name` (or VIEW/PROCEDURE/FUNCTION/EVENT) through `/profiles/<profile>/query`. In `/profiles/<profile>/ddl`'s `table` parameter, backtick-quote names containing commas.

A NULL routine definition or `missing source code` view means source is unavailable to the account, not empty.

## Errors

Errors are plain text even with `format=json`; check HTTP status before decoding. Diagnose from the response message; do not blindly retry syntax or permission errors.
