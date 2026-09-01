from app.database import db_session
from app.executor import RawQueryValue, run_raw_sql, run_sql
from app.sql_guard import clean_select_sql, clean_sql, count_sql, explain_sql, first_word, paged_sql


def query_text(profile: str, sql: str, limit: int, offset: int) -> str:
    """执行 SELECT/WITH/SHOW；仅 SELECT/WITH 添加 LIMIT/OFFSET。"""
    readonly_sql = clean_sql(sql)
    with db_session(profile) as session:
        if first_word(readonly_sql) == "show":
            return run_sql(session, readonly_sql)
        sql, params = paged_sql(readonly_sql, limit=limit, offset=offset)
        return run_sql(session, sql, params=params)


def query_raw(profile: str, sql: str) -> RawQueryValue:
    """执行一行一列查询，保留字段原始内容。"""
    readonly_sql = clean_sql(sql)
    with db_session(profile) as session:
        if first_word(readonly_sql) == "show":
            return run_raw_sql(session, readonly_sql)
        raw_sql, params = paged_sql(readonly_sql, limit=2, offset=0)
        return run_raw_sql(session, raw_sql, params=params)


def count_text(profile: str, sql: str) -> str:
    """统计 SELECT/WITH 查询结果数量。"""
    readonly_sql = clean_select_sql(sql)
    with db_session(profile) as session:
        return run_sql(session, count_sql(readonly_sql))


def explain_text(profile: str, sql: str) -> str:
    """查看 SELECT/WITH 查询执行计划。"""
    readonly_sql = clean_select_sql(sql)
    with db_session(profile) as session:
        return run_sql(session, explain_sql(readonly_sql))
