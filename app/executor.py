from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from app.text_format import format_text_rows


def run_sql(session: Session, sql: str, params: Mapping[str, Any] | None = None) -> str:
    """执行 SQL 并返回纯文本结果。"""
    result = session.exec(text(sql), params=params)
    if not result.returns_rows:
        return "OK"
    return format_text_rows(list(result.keys()), result.fetchall())
