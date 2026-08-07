from app.database import db_session
from app.executor import run_sql
from app.sql_guard import clean_sql, count_sql, explain_sql, paged_sql


def query_text(profile: str, sql: str, limit: int, offset: int) -> str:
    """执行 SELECT/WITH 查询，并在 SQL 外层添加 LIMIT/OFFSET。"""
    readonly_sql = clean_sql(sql)
    sql, params = paged_sql(readonly_sql, limit=limit, offset=offset)
    with db_session(profile) as session:
        return run_sql(session, sql, params=params)


def count_text(profile: str, sql: str) -> str:
    """统计 SELECT/WITH 查询结果数量。"""
    readonly_sql = clean_sql(sql)
    with db_session(profile) as session:
        return run_sql(session, count_sql(readonly_sql))


def explain_text(profile: str, sql: str) -> str:
    """查看 SELECT/WITH 查询执行计划。"""
    readonly_sql = clean_sql(sql)
    with db_session(profile) as session:
        return run_sql(session, explain_sql(readonly_sql))
