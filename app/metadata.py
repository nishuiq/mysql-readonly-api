"""查询账号可见的业务 schema、表和视图元数据"""

from typing import Any

from sqlmodel import Session

from app.executor import QueryResult, run_sql


def list_schemas(session: Session, limit: int) -> QueryResult:
    """列出账号可见的非系统 schema

    Args:
        session: 当前请求的只读会话
        limit: 最多返回的 schema 数量

    Returns:
        按名称排序的 schema 结果，超出上限时标记截断

    Raises:
        SQLAlchemyError: 元数据查询失败
    """
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
    """列出指定 schema 下匹配关键字的表和视图

    Args:
        session: 当前请求的只读会话
        schema: 目标 schema 名称
        keyword: 匹配名称或注释的 LIKE 片段，空字符串表示不筛选
        limit: 最多返回的对象数量

    Returns:
        按名称排序的对象结果，表行数为数据库估计值

    Raises:
        SQLAlchemyError: 元数据查询失败
    """
    sql, params = table_search_sql(schema, keyword)
    params["fetch_limit"] = limit + 1
    return run_sql(session, sql + "\nLIMIT :fetch_limit", params=params, limit=limit)


def table_search_sql(schema: str, keyword: str) -> tuple[str, dict[str, Any]]:
    """构造表和视图搜索的绑定参数查询

    Args:
        schema: 目标 schema 名称
        keyword: 匹配名称或注释的 LIKE 片段，保留调用方提供的通配符

    Returns:
        尚未追加行数上限的 SQL 模板及其参数映射
    """
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
