"""协调只读 SQL 校验、结果分页、计数和执行计划查询"""

from fastapi import HTTPException
from sqlmodel import Session

from app.executor import QueryResult, run_query
from app.sql_guard import clean_select_sql, clean_sql, count_sql, explain_sql, first_word, paged_sql


def query_result(session: Session, sql: str, limit: int, offset: int) -> QueryResult:
    """执行 SELECT/WITH 或 SHOW 并限制返回行数

    Args:
        session: 附带实际 SQL mode 的只读会话
        sql: 调用方提交的单条 SQL
        limit: 已经校验的返回行数上限
        offset: SELECT/WITH 的外层结果偏移量，SHOW 必须为零

    Returns:
        统一结果集，SELECT 多取一行，SHOW 在驱动结果中判断截断

    Raises:
        HTTPException: SQL 不符合只读规则或 SHOW 使用非零偏移量
        SQLAlchemyError: 数据库执行失败
    """
    mode = session.info["sql_mode"]
    readonly_sql = clean_sql(sql, mode)
    if first_word(readonly_sql, mode) == "show":
        if offset:
            raise HTTPException(422, "SHOW does not support API offset; use information_schema SELECT for paging.")
        return run_query(session, readonly_sql, limit=limit)
    return run_query(session, paged_sql(readonly_sql, limit, offset), limit=limit)


def count_result(session: Session, sql: str) -> QueryResult:
    """统计提交的 SELECT/WITH 查询产生的结果行数

    Args:
        session: 附带实际 SQL mode 的只读会话
        sql: 调用方 SQL，内层 LIMIT 会影响最终计数

    Returns:
        包含 count 列和单行计数的结果

    Raises:
        HTTPException: SQL 不符合 SELECT/WITH 只读规则
        SQLAlchemyError: 计数查询执行失败
    """
    readonly_sql = clean_select_sql(sql, session.info["sql_mode"])
    return run_query(session, count_sql(readonly_sql))


def explain_result(session: Session, sql: str, limit: int) -> QueryResult:
    """查询提交 SQL 的 MySQL 执行计划

    Args:
        session: 附带实际 SQL mode 的只读会话
        sql: 调用方提交的 SELECT/WITH SQL
        limit: 最多保留的计划结果行数

    Returns:
        原生 EXPLAIN 结果，超出返回上限时标记截断

    Raises:
        HTTPException: SQL 不符合 SELECT/WITH 只读规则
        SQLAlchemyError: 执行计划查询失败
    """
    readonly_sql = clean_select_sql(sql, session.info["sql_mode"])
    return run_query(session, explain_sql(readonly_sql), limit=limit)
