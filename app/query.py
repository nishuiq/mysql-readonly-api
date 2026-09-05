from fastapi import HTTPException
from sqlmodel import Session

from app.executor import QueryResult, run_query
from app.sql_guard import clean_select_sql, clean_sql, count_sql, explain_sql, first_word, paged_sql


def query_result(session: Session, sql: str, limit: int, offset: int) -> QueryResult:
    mode = session.info["sql_mode"]
    readonly_sql = clean_sql(sql, mode)
    if first_word(readonly_sql, mode) == "show":
        if offset:
            raise HTTPException(422, "SHOW does not support API offset; use information_schema SELECT for paging.")
        return run_query(session, readonly_sql, limit=limit)
    return run_query(session, paged_sql(readonly_sql, limit, offset), limit=limit)


def count_result(session: Session, sql: str) -> QueryResult:
    readonly_sql = clean_select_sql(sql, session.info["sql_mode"])
    return run_query(session, count_sql(readonly_sql))


def explain_result(session: Session, sql: str, limit: int) -> QueryResult:
    readonly_sql = clean_select_sql(sql, session.info["sql_mode"])
    return run_query(session, explain_sql(readonly_sql), limit=limit)
