import re
from typing import Any

from fastapi import HTTPException

ALLOWED_FIRST_WORDS = {"select", "with"}
FORBIDDEN_WORDS = re.compile(
    r"\b(outfile|dumpfile|load_file)\b",
    re.IGNORECASE,
)


def clean_sql(sql: str) -> str:
    """做最小只读 SQL 检查。"""
    cleaned = sql.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="SQL is empty.")

    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()

    if ";" in cleaned:
        raise HTTPException(status_code=400, detail="Only one SQL statement is allowed.")

    if first_word(cleaned) not in ALLOWED_FIRST_WORDS:
        raise HTTPException(status_code=400, detail="Only SELECT or WITH SQL is allowed.")

    if FORBIDDEN_WORDS.search(cleaned):
        raise HTTPException(status_code=400, detail="SQL contains forbidden keyword.")

    return cleaned


def first_word(sql: str) -> str:
    """跳过开头注释后读取 SQL 首个关键字。"""
    remaining = sql.lstrip()
    while True:
        if remaining.startswith("--"):
            _, _, remaining = remaining.partition("\n")
            remaining = remaining.lstrip()
            continue
        if remaining.startswith("#"):
            _, _, remaining = remaining.partition("\n")
            remaining = remaining.lstrip()
            continue
        if remaining.startswith("/*"):
            end = remaining.find("*/")
            if end == -1:
                return ""
            remaining = remaining[end + 2 :].lstrip()
            continue
        break

    match = re.match(r"([a-zA-Z]+)", remaining)
    return match.group(1).lower() if match else ""


def paged_sql(sql: str, limit: int, offset: int) -> tuple[str, dict[str, Any]]:
    """将查询包成带 LIMIT/OFFSET 的外层 SQL。"""
    return (
        f"""
        SELECT *
        FROM (
            {sql}
        ) AS _codex_query
        LIMIT :_codex_limit OFFSET :_codex_offset
        """,
        {"_codex_limit": limit, "_codex_offset": offset},
    )


def count_sql(sql: str) -> str:
    """将查询包成 count SQL。"""
    return f"SELECT COUNT(*) AS count FROM ({sql}) AS _count_query"
