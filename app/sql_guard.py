"""检查单条 MySQL 只读 SQL 和最外层行数限制"""

from dataclasses import dataclass
from typing import NoReturn

from fastapi import HTTPException
from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from app.config import MAX_QUERY_LIMIT

ALLOWED_FIRST_WORDS = {"select", "show", "with", "explain"}
FORBIDDEN_WORDS = {"insert", "update", "delete", "replace", "into"}
READ_FUNCTIONS = {"insert", "replace"}
LOCKING_PHRASES = (("for", "share"), ("lock", "in", "share", "mode"))
FORBIDDEN_FUNCTIONS = {
    "load_file",
    "sleep",
    "benchmark",
    "get_lock",
    "release_lock",
    "release_all_locks",
    "is_free_lock",
    "is_used_lock",
    "wait_for_executed_gtid_set",
    "wait_until_sql_thread_after_gtids",
    "master_pos_wait",
    "source_pos_wait",
}


@dataclass(frozen=True, slots=True)
class Token:
    """表示一个参与只读检查的 SQL 词法单元

    Attributes:
        value: 归一化的词法内容，字符串字面量使用占位值
        quoted: 是否来自字符串或带引用的标识符，不按普通关键字处理
    """

    value: str
    quoted: bool = False


@dataclass(frozen=True, slots=True)
class ValidatedSql:
    """表示已通过检查的 SQL 与最外层行数限制

    Attributes:
        sql: 未改写的用户 SQL
        statement: 首个未引用关键字的小写形式
        limit: 最外层 LIMIT 的行数，不存在时为 None
    """

    sql: str
    statement: str
    limit: int | None


def tokens(sql: str, sql_mode: str = "") -> list[Token]:
    """识别 SQL 字符串、标识符和语句边界并拒绝注释

    Args:
        sql: 待扫描的 SQL 原文
        sql_mode: 实际会话模式，影响反斜杠转义和双引号含义

    Returns:
        按原始顺序排列的词法单元

    Raises:
        HTTPException: 输入包含注释或字符串、标识符未闭合
    """
    modes = set(sql_mode.upper().split(","))
    result: list[Token] = []
    i = 0
    while i < len(sql):
        char = sql[i]
        if char.isspace():
            i += 1
            continue
        if char == "#" or sql.startswith("/*", i):
            raise_sql_error("SQL comments are not allowed.")
        if sql.startswith("--", i) and (i + 2 == len(sql) or ord(sql[i + 2]) <= 32 or sql[i + 2] == "\x7f"):
            raise_sql_error("SQL comments are not allowed.")
        start = i
        if char in "'\"\x60":
            identifier = char == "\x60" or (char == '"' and "ANSI_QUOTES" in modes)
            i += 1
            while i < len(sql):
                if sql[i] == char:
                    i += 1
                    if i < len(sql) and sql[i] == char:
                        i += 1
                        continue
                    break
                if sql[i] == "\\" and not identifier and "NO_BACKSLASH_ESCAPES" not in modes:
                    i += 2
                else:
                    i += 1
            else:
                raise_sql_error("Unterminated SQL string or identifier.")
            value = sql[start + 1 : i - 1].replace(char * 2, char).lower() if identifier else "<string>"
            result.append(Token(value, quoted=True))
            continue
        if char.isalnum() or char in "_$":
            i += 1
            while i < len(sql) and (sql[i].isalnum() or sql[i] in "_$"):
                i += 1
            result.append(Token(sql[start:i].lower()))
            continue
        pair = sql[i : i + 2]
        if pair in {"@@", ":="}:
            result.append(Token(pair))
            i += 2
        else:
            result.append(Token(char))
            i += 1
    return result


def limit_number(value: str) -> int:
    """读取 SQL 中的行数并拒绝超过固定上限的值

    Args:
        value: 未引用的十进制行数字面量

    Returns:
        不超过 5000 的非负行数

    Raises:
        HTTPException: 行数不是十进制整数或超过上限
    """
    if not value.isascii() or not value.isdigit():
        raise_sql_error("SQL LIMIT must be a non-negative integer.")
    normalized = value.lstrip("0") or "0"
    maximum = str(MAX_QUERY_LIMIT)
    if len(normalized) > len(maximum) or (len(normalized) == len(maximum) and normalized > maximum):
        raise_sql_error(f"SQL LIMIT must be at most {MAX_QUERY_LIMIT}.")
    return int(normalized)


def outer_limit(parsed: list[Token]) -> int | None:
    """从词法单元中读取最外层 LIMIT 的行数

    Args:
        parsed: 已识别字符串和标识符边界的 SQL 单元

    Returns:
        最外层 LIMIT 的行数，不存在时为 None

    Raises:
        HTTPException: 最外层 LIMIT 不完整、不是整数或超过上限
    """
    depth = 0
    index = None
    for position, token in enumerate(parsed):
        if token.quoted:
            continue
        if token.value == "(":
            depth += 1
        elif token.value == ")":
            depth -= 1
        elif token.value == "limit" and depth == 0 and (position == 0 or parsed[position - 1].value != "."):
            if index is not None:
                raise_sql_error("Only one outer SQL LIMIT is allowed.")
            index = position
    if index is None:
        return None
    count_position = index + 1
    if count_position + 1 < len(parsed) and parsed[count_position + 1].value == ",":
        count_position += 2
    if count_position >= len(parsed) or parsed[count_position].quoted:
        raise_sql_error("SQL LIMIT must be a non-negative integer.")
    return limit_number(parsed[count_position].value)


def validate_sql(sql: str, sql_mode: str = "") -> ValidatedSql:
    """校验单条只读查询并识别最外层限制

    Args:
        sql: 调用方提交的单条 SQL
        sql_mode: 当前连接使用的引用和转义模式

    Returns:
        未改写的 SQL、语句类型和最外层 LIMIT

    Raises:
        HTTPException: SQL 不符合只读规则、无法解析或最外层 LIMIT 超过 5000
    """
    parsed = tokens(sql, sql_mode)
    if not parsed:
        raise_sql_error("SQL is empty.")
    words = [token.value if not token.quoted else "" for token in parsed]
    if ";" in words:
        raise_sql_error("SQL statement separators are not allowed.")
    if words[0] not in ALLOWED_FIRST_WORDS:
        raise_sql_error("Only SELECT, WITH, SHOW or EXPLAIN SQL is allowed.")
    if words[:2] == ["explain", "analyze"]:
        raise_sql_error("EXPLAIN ANALYZE is not allowed.")
    for index, token in enumerate(parsed):
        value = token.value
        next_value = words[index + 1] if index + 1 < len(words) else ""
        if not token.quoted and value in {"@", ":="}:
            raise_sql_error("User variables and assignments are not allowed; @@ system reads are allowed.")
        if value in FORBIDDEN_FUNCTIONS and next_value == "(":
            raise_sql_error(f"Function {value.upper()}() is not allowed.")
        if words[0] != "show" and not token.quoted:
            qualified = index > 0 and words[index - 1] == "."
            function = value in READ_FUNCTIONS and next_value == "("
            if value in FORBIDDEN_WORDS and not qualified and not function:
                raise_sql_error(f"Keyword {value.upper()} is not allowed in a read query.")
            if any(tuple(words[index : index + len(phrase)]) == phrase for phrase in LOCKING_PHRASES):
                raise_sql_error("Locking reads are not allowed.")

    lexical_limit = outer_limit(parsed)
    if words[0] == "show":
        return ValidatedSql(sql, words[0], lexical_limit)
    try:
        # 解析回退时不向日志输出用户 SQL
        statements = parse(sql, read="mysql", error_message_context=0)
    except SqlglotError:
        raise_sql_error("SQL cannot be parsed as a MySQL read query.")
    if len(statements) != 1 or statements[0] is None:
        raise_sql_error("Only one SQL statement is allowed.")
    statement = statements[0]
    if words[0] == "explain":
        if not isinstance(statement, exp.Describe) or not isinstance(statement.this, exp.Query):
            raise_sql_error("Only EXPLAIN of a SELECT or WITH query is allowed.")
        if str(statement.args.get("style", "")).upper() == "ANALYZE":
            raise_sql_error("EXPLAIN ANALYZE is not allowed.")
        statement = statement.this
    if not isinstance(statement, exp.Query):
        raise_sql_error("Only SELECT or WITH queries are allowed.")
    limit = statement.args.get("limit")
    if limit is None:
        ast_limit = None
    elif isinstance(limit, exp.Limit) and isinstance(limit.expression, exp.Literal) and not limit.expression.is_string:
        ast_limit = limit_number(str(limit.expression.this))
    else:
        raise_sql_error("SQL LIMIT must be a non-negative integer.")
    if ast_limit != lexical_limit:
        raise_sql_error("Cannot reliably inspect the outer SQL LIMIT.")
    return ValidatedSql(sql, words[0], lexical_limit)


def raise_sql_error(detail: str) -> NoReturn:
    """中止请求并报告 SQL 规则错误

    Args:
        detail: 供调用方纠正 SQL 的错误说明

    Raises:
        HTTPException: 始终抛出状态为 400 的异常
    """
    raise HTTPException(status_code=400, detail=detail)
