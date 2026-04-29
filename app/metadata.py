from __future__ import annotations

from typing import Any

from app.database import db_session
from app.executor import run_sql


def list_schemas() -> str:
    """列出业务 schema。"""
    with db_session() as session:
        return run_sql(
            session,
            """
            SELECT SCHEMA_NAME AS `Database`
            FROM information_schema.SCHEMATA
            WHERE SCHEMA_NAME NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
            ORDER BY SCHEMA_NAME
            """,
        )


def list_tables(schema: str, keyword: str = "") -> str:
    """按 schema 和关键字搜索表。"""
    sql, params = table_search_sql(schema=schema, keyword=keyword)
    with db_session() as session:
        return run_sql(session, sql, params=params)


def table_search_sql(schema: str, keyword: str) -> tuple[str, dict[str, Any]]:
    """生成表搜索 SQL。"""
    params: dict[str, Any] = {"schema": schema}
    where = "TABLE_SCHEMA = :schema"
    if keyword:
        where += " AND (TABLE_NAME LIKE :keyword OR TABLE_COMMENT LIKE :keyword)"
        params["keyword"] = f"%{keyword}%"
    sql = f"""
        SELECT
            TABLE_NAME AS Name,
            TABLE_COMMENT AS Comment,
            TABLE_ROWS AS EstimateRows
        FROM information_schema.TABLES
        WHERE {where}
        ORDER BY TABLE_NAME
    """
    return sql, params
