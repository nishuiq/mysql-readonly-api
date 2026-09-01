from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, text

from app.text_format import format_text_rows


@dataclass(frozen=True)
class RawQueryValue:
    """一行一列 raw 查询的字段名和值。"""

    column: str
    value: Any


def run_sql(session: Session, sql: str, params: Mapping[str, Any] | None = None) -> str:
    """执行 SQL 并返回纯文本结果。"""
    result = session.exec(text(sql), params=params)
    if not result.returns_rows:
        return "OK"
    return format_text_rows(
        list(result.keys()),
        result.fetchall(),
        zero_datetime_behavior=str(session.info.get("zero_datetime_behavior", "")),
    )


def run_raw_sql(session: Session, sql: str, params: Mapping[str, Any] | None = None) -> RawQueryValue:
    """执行 SQL，并要求结果恰好为一行一列。"""
    result = session.exec(text(sql), params=params)
    if not result.returns_rows:
        raise_raw_shape_error("Raw query must return rows.")

    columns = list(result.keys())
    if len(columns) != 1:
        raise_raw_shape_error("Raw query must return exactly one column.")

    rows = result.fetchmany(2)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Raw query returned no row.",
        )
    if len(rows) != 1:
        raise_raw_shape_error("Raw query must return exactly one row.")
    return RawQueryValue(column=str(columns[0]), value=rows[0][0])


def raise_raw_shape_error(detail: str) -> None:
    """抛出 raw 查询结果形状错误。"""
    raise HTTPException(status_code=400, detail=detail)
