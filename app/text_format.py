from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, Response


def format_value(value: Any, zero_datetime_behavior: str = "") -> str:
    """将数据库值转换成单行文本。"""
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + value.hex()
    if should_convert_zero_datetime(value, zero_datetime_behavior):
        return "NULL"
    if isinstance(value, (datetime, date, time, Decimal)):
        return str(value)
    text_value = str(value)
    return text_value.replace("\r", "\\r").replace("\n", "\\n")


def should_convert_zero_datetime(value: Any, zero_datetime_behavior: str) -> bool:
    """判断是否需要把 MySQL 零日期转成 NULL。"""
    return zero_datetime_behavior == "convert_to_null" and isinstance(value, str) and value.startswith("0000-00-00")


def format_text_rows(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    zero_datetime_behavior: str = "",
) -> str:
    """将结果集渲染成 tab 分隔文本。"""
    if not columns:
        return "OK"

    formatted_rows = [[format_value(value, zero_datetime_behavior) for value in row] for row in rows]
    lines = ["\t".join(columns)]
    lines.extend("\t".join(row) for row in formatted_rows)
    return "\n".join(lines)


def raw_value_response(column: str, value: Any) -> Response:
    """返回“单列表头 + 原始字段内容”，不转义字段值。"""
    if "\r" in column or "\n" in column:
        raise HTTPException(
            status_code=400,
            detail="Raw query column name must be a single line.",
        )

    if value is None:
        return Response(status_code=204)

    prefix = column.encode("utf-8") + b"\n"
    if isinstance(value, bytes):
        return Response(
            content=prefix + value,
            media_type="text/plain; charset=utf-8",
        )
    return Response(
        content=prefix + str(value).encode("utf-8"),
        media_type="text/plain; charset=utf-8",
    )


def text_response(content: str, status_code: int = 200) -> Response:
    """构造纯文本 HTTP 响应。"""
    return Response(
        content=content,
        status_code=status_code,
        media_type="text/plain; charset=utf-8",
    )
