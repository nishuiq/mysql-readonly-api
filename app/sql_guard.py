import re
from typing import Any

from fastapi import HTTPException

ALLOWED_FIRST_WORDS = {"select", "show", "with"}
SELECT_FIRST_WORDS = {"select", "with"}
COMMENT_PATTERN = re.compile(r"/\*|--|#", re.IGNORECASE)
FORBIDDEN_PATTERNS = (
    COMMENT_PATTERN,
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
    """做最小只读 SQL 检查，允许 SELECT/WITH/SHOW。"""
    cleaned = sql.strip()
    if not cleaned:
        raise_sql_error("SQL is empty.")

    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()

    if ";" in cleaned:
        raise_sql_error("Only one SQL statement is allowed.")

    word = first_word(cleaned)
    if word not in ALLOWED_FIRST_WORDS:
        raise_sql_error("Only SELECT, WITH or SHOW SQL is allowed.")

    # SHOW 是只读元数据语句，但 SHOW CREATE 本身包含 CREATE 关键字，
    # 不能套用 SELECT 的禁词规则。仍禁止注释和多语句。
    if word == "show":
        if COMMENT_PATTERN.search(cleaned):
            raise_sql_error("SQL comments are not allowed.")
        return cleaned

    if has_forbidden_pattern(cleaned):
        raise_sql_error("SQL contains forbidden keyword.")

    return cleaned


def clean_select_sql(sql: str) -> str:
    """清理只允许 SELECT/WITH 的 SQL，用于 count 和 explain。"""
    cleaned = clean_sql(sql)
    if first_word(cleaned) not in SELECT_FIRST_WORDS:
        raise_sql_error("Only SELECT or WITH SQL is allowed for this operation.")
    return cleaned


def raise_sql_error(detail: str) -> None:
    """抛出 SQL 请求异常。"""
    raise HTTPException(status_code=400, detail=detail)


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
