import re
from typing import Any

from fastapi import HTTPException

ALLOWED_FIRST_WORDS = {"select", "with"}
FORBIDDEN_PATTERNS = (
    re.compile(r"/\*|--|#", re.IGNORECASE),
    re.compile(
        r"\b("
        r"insert|update|delete|replace|drop|alter|create|truncate|rename|"
        r"grant|revoke|set|use|call|do|handler|load|"
        r"lock|unlock|begin|start|commit|rollback|savepoint|"
        r"prepare|execute|deallocate|analyze|optimize|repair|kill"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b("
        r"for\s+update|lock\s+in\s+share\s+mode|for\s+share|nowait|skip\s+locked|"
        # 拦截所有 SELECT ... INTO 变体，包括 OUTFILE/DUMPFILE 文件写出，
        # 以及用户变量/局部变量赋值。
        r"into"
        r")\b",
        re.IGNORECASE,
    ),
    # 拦截 MySQL 用户/session 变量和表达式级赋值。
    re.compile(r"@\w+|:=", re.IGNORECASE),
    re.compile(
        r"\b("
        r"load_file|sleep|benchmark|get_lock|release_lock|release_all_locks|is_free_lock|is_used_lock"
        r")\s*\(",
        re.IGNORECASE,
    ),
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

    if has_forbidden_pattern(cleaned):
        raise HTTPException(status_code=400, detail="SQL contains forbidden keyword.")

    return cleaned


def has_forbidden_pattern(sql: str) -> bool:
    """判断 SQL 是否包含明确禁止的高风险行为。"""
    return any(pattern.search(sql) for pattern in FORBIDDEN_PATTERNS)


def first_word(sql: str) -> str:
    """读取 SQL 首个关键字。"""
    match = re.match(r"([a-zA-Z]+)", sql.lstrip())
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


def explain_sql(sql: str) -> str:
    """生成 EXPLAIN SQL。"""
    return f"EXPLAIN {sql}"
