from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import Response
from starlette.responses import JSONResponse

from app.executor import QueryResult

OutputFormat = Literal["text", "json"]


def time_interval(value: timedelta) -> str:
    """MySQL TIME 是可超过 24 小时、可为负数的时长。"""
    micros = (value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds
    sign = "-" if micros < 0 else ""
    seconds, fraction = divmod(abs(micros), 1_000_000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    suffix = f".{fraction:06d}" if fraction else ""
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}{suffix}"


def json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    if isinstance(value, timedelta):
        return time_interval(value)
    if isinstance(value, (Decimal, datetime, date, time)):
        return str(value)
    return value


def format_value(value: Any) -> str:
    """文本展示不改写字符串；NULL 和二进制使用明确的展示约定。"""
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, timedelta):
        return time_interval(value)
    return str(value)


def format_text_rows(columns: Sequence[str], rows: Sequence[Sequence[Any]], truncated: bool = False) -> str:
    lines = ["[truncated]"] if truncated else []
    lines.append("\t".join(columns) if columns else "OK")
    lines.extend("\t".join(format_value(value) for value in row) for row in rows)
    return "\n".join(lines)


def result_response(result: QueryResult, output_format: OutputFormat = "text") -> Response:
    if output_format == "json":
        return JSONResponse(
            {
                "columns": result.columns,
                "rows": [[json_value(value) for value in row] for row in result.rows],
                "truncated": result.truncated,
            }
        )
    return text_response(format_text_rows(result.columns, result.rows, result.truncated))


def text_response(content: str, status_code: int = 200) -> Response:
    return Response(content=content, status_code=status_code, media_type="text/plain; charset=utf-8")
