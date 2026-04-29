from __future__ import annotations

from collections.abc import Sequence


def parse_table_names(table: Sequence[str]) -> list[str]:
    """解析 table 查询参数，支持重复参数和逗号分隔。"""
    table_names: list[str] = []
    for item in table:
        table_names.extend(name.strip() for name in item.split(",") if name.strip())
    return table_names
