from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, text


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool = False


def read_result(result: Any, limit: int | None = None) -> QueryResult:
    if not result.returns_rows:
        return QueryResult([], [])
    columns = [str(column) for column in result.keys()]
    rows = result.fetchall() if limit is None else result.fetchmany(limit + 1)
    truncated = limit is not None and len(rows) > limit
    return QueryResult(columns, [tuple(row) for row in rows[:limit]], truncated)


def run_query(session: Session, sql: str, limit: int | None = None) -> QueryResult:
    """原始 SQL 不参与参数模板解释；冒号、百分号及反斜杠保持原义。"""
    with session.connection().exec_driver_sql(sql, execution_options={"no_parameters": True}) as result:
        return read_result(result, limit)


def run_sql(
    session: Session, sql: str, params: Mapping[str, Any] | None = None, limit: int | None = None
) -> QueryResult:
    """服务内部构造的元数据 SQL 使用绑定参数。"""
    with session.exec(text(sql), params=params) as result:
        return read_result(result, limit)
