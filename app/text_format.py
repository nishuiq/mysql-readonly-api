"""将数据库结果表示为保留字符串原值的文本或紧凑 JSON"""

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
    """按 MySQL TIME 语义显示可为负数的时长

    Args:
        value: 驱动返回的时长，可以超过 24 小时

    Returns:
        带可选负号的 HH:MM:SS，存在微秒时追加六位小数
    """
    micros = (value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds
    sign = "-" if micros < 0 else ""
    seconds, fraction = divmod(abs(micros), 1_000_000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    suffix = f".{fraction:06d}" if fraction else ""
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}{suffix}"


def json_value(value: Any) -> Any:
    """将单个驱动值转换为可编码的 JSON 值

    Args:
        value: 数据库字段原值，包括 None、日期、Decimal 和 bytes

    Returns:
        字符串保持原值，日期和 Decimal 转字符串，时长转 TIME 文本，bytes 转 hex 对象
    """
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    if isinstance(value, timedelta):
        return time_interval(value)
    if isinstance(value, (Decimal, datetime, date, time)):
        return str(value)
    return value


def format_value(value: Any) -> str:
    """生成单个字段的文本展示

    Args:
        value: 数据库字段原值，包括 None 和二进制

    Returns:
        None 显示 NULL，bytes 显示十六进制，字符串中的控制字符和反斜杠保持原样
    """
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, timedelta):
        return time_interval(value)
    return str(value)


def format_text_rows(columns: Sequence[str], rows: Sequence[Sequence[Any]], truncated: bool = False) -> str:
    """按列和行顺序拼接供阅读的结果文本

    Args:
        columns: 列名序列，空序列表示没有结果列
        rows: 按列顺序组织的字段序列
        truncated: 是否在表头前添加独立的截断标记行

    Returns:
        用 tab 分隔字段、LF 分隔记录的文本，标记与表头间没有空行，格式可能存在字段歧义
    """
    lines = ["[truncated]"] if truncated else []
    lines.append("\t".join(columns) if columns else "OK")
    lines.extend("\t".join(format_value(value) for value in row) for row in rows)
    return "\n".join(lines)


def result_response(result: QueryResult, output_format: OutputFormat = "text") -> Response:
    """按所选格式生成成功的结果响应

    Args:
        result: 包含列、行和截断状态的统一结果
        output_format: text 或 json，省略时使用 text

    Returns:
        文本或紧凑 JSON 响应，空结果仍返回 200
    """
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
    """构造 UTF-8 纯文本 HTTP 响应

    Args:
        content: 未经额外转义的响应文本
        status_code: HTTP 状态码，省略时为 200

    Returns:
        带 text/plain 字符集声明的响应对象
    """
    return Response(content=content, status_code=status_code, media_type="text/plain; charset=utf-8")
