from typing import Any

from sqlmodel import Session

from app.executor import QueryResult, run_sql


def list_schemas(session: Session, limit: int) -> QueryResult:
    return run_sql(
        session,
        """
        SELECT SCHEMA_NAME AS `Database`
        FROM information_schema.SCHEMATA
        WHERE SCHEMA_NAME NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
        ORDER BY SCHEMA_NAME
        LIMIT :fetch_limit
        """,
        {"fetch_limit": limit + 1},
        limit=limit,
    )


def list_tables(session: Session, schema: str, keyword: str, limit: int) -> QueryResult:
    sql, params = table_search_sql(schema, keyword)
    params["fetch_limit"] = limit + 1
    return run_sql(session, sql + "\nLIMIT :fetch_limit", params=params, limit=limit)


def table_search_sql(schema: str, keyword: str) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {"schema": schema}
    where = "TABLE_SCHEMA = :schema"
    if keyword:
        where += " AND (TABLE_NAME LIKE :keyword OR TABLE_COMMENT LIKE :keyword)"
        params["keyword"] = f"%{keyword}%"
    return (
        f"""
        SELECT TABLE_NAME AS Name, TABLE_TYPE AS Type,
               TABLE_COMMENT AS Comment, TABLE_ROWS AS EstimateRows
        FROM information_schema.TABLES
        WHERE {where}
        ORDER BY TABLE_NAME
    """,
        params,
    )
