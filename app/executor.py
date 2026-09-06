"""执行 SQL 并将有限结果集转换为统一的内存表示"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, text


@dataclass(frozen=True)
class QueryResult:
    """表示一个结果集及其截断状态

    Attributes:
        columns: 按驱动顺序排列的列名，允许重复
        rows: 按列顺序排列的行，不修改驱动返回的字段值
        truncated: 是否读取到了返回行数上限之外的额外一行
    """

    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool = False


def read_result(result: Any, limit: int | None = None) -> QueryResult:
    """读取列名和结果行并根据额外一行判断截断

    Args:
        result: 尚未关闭的 SQLAlchemy 结果游标
        limit: 最多保留的行数，为 None 时读取全部结果

    Returns:
        保留字段原值的结果集，不返回额外探测行，没有结果列时为空
    """
    if not result.returns_rows:
        return QueryResult([], [])
    columns = [str(column) for column in result.keys()]
    rows = result.fetchall() if limit is None else result.fetchmany(limit + 1)
    truncated = limit is not None and len(rows) > limit
    return QueryResult(columns, [tuple(row) for row in rows[:limit]], truncated)


def run_query(session: Session, sql: str, limit: int | None = None) -> QueryResult:
    """将用户 SQL 直接交给驱动执行

    Args:
        session: 当前请求的只读会话
        sql: 已通过校验的完整 SQL，不作为绑定参数模板解释
        limit: 最多保留的行数，为 None 时读取全部结果

    Returns:
        统一的查询结果，游标会在读取后关闭

    Raises:
        SQLAlchemyError: 数据库拒绝 SQL 或执行过程中连接失败
    """
    with session.connection().exec_driver_sql(sql, execution_options={"no_parameters": True}) as result:
        return read_result(result, limit)


def run_sql(
    session: Session, sql: str, params: Mapping[str, Any] | None = None, limit: int | None = None
) -> QueryResult:
    """通过绑定参数执行服务内部构造的 SQL

    Args:
        session: 当前请求的只读会话
        sql: 服务内部的 SQL 模板
        params: 模板参数映射，为 None 时不提供绑定参数
        limit: 最多保留的行数，为 None 时读取全部结果

    Returns:
        统一的查询结果，游标会在读取后关闭

    Raises:
        SQLAlchemyError: 模板执行或结果读取失败
    """
    with session.exec(text(sql), params=params) as result:
        return read_result(result, limit)
