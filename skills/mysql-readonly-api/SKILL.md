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
| `POST /profiles/<profile>/query` | SELECT/WITH/SHOW | Rows |
| `POST /profiles/<profile>/count` | SELECT/WITH | Result count |
| `POST /profiles/<profile>/explain` | SELECT/WITH | Execution plan |

Send POST SQL directly as UTF-8 `text/plain`. URL-encode query parameters.

`query`, `schemas`, `tables` and `explain` accept `limit`: a positive integer defaulting to the configured `query.limit`, which is also the hard cap. Query `offset` is nonnegative and defaults to 0.

## Results

`/profiles/<profile>/ddl` is text-only. For other endpoints, prefer default text (omit `format`) for browsing and ordinary queries.

Use `format=json` for programmatic row/field processing, verbatim source extraction, or distinguishing SQL NULL from the string `"NULL"`.

- Text has a header and tab-separated fields; strings retain tabs, CR/LF and backslashes. SQL NULL and `"NULL"` both display as `NULL`.
- JSON: `{"columns":["a","b"],"rows":[[1,null]],"truncated":false}`.
- Decimal/date/time values are strings; TIME can be negative or exceed 24 hours. Binary values are `{"hex":"..."}` in JSON and `0x...` in text.
- Truncation: `[truncated]` on a line immediately before the text header, or JSON `truncated:true`. Empty results succeed with a header only or `rows:[]`.

## Query rules

Send one statement per request. Ordinary comments, a trailing semicolon and `@@` reads are allowed; user variables, locking reads, file/wait/lock functions, executable comments and optimizer hints are rejected. MySQL 5.7 has no CTE support.

- SELECT/WITH in `/profiles/<profile>/query` uses outer LIMIT/OFFSET. Query/count require unique projected column names; inner LIMIT affects both truncation and count. Count only when a total is needed; it may be expensive.
- For stable page selection, use a unique ORDER BY and LIMIT in SQL, with OFFSET or a keyset predicate to advance. Keep API offset 0 and SQL page size within the API limit.
- The wrapper does not promise returned row order; sort the returned page if required. Requests do not share a snapshot.
- SHOW requires API offset 0. For truncated metadata, narrow filters or query `information_schema` for paging.

## Definitions

For native definitions, use `SHOW CREATE TABLE schema.name` (or VIEW/PROCEDURE/FUNCTION/EVENT) through `/profiles/<profile>/query`. In `/profiles/<profile>/ddl`'s `table` parameter, backtick-quote names containing commas.

A NULL routine definition or `missing source code` view means source is unavailable to the account, not empty.

## Errors

Errors are plain text even with `format=json`; check HTTP status before decoding. Diagnose from the response message; do not blindly retry syntax or permission errors.
