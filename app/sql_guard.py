"""按 MySQL 词法边界检查只读 SQL 并构造外层结果查询"""

import re
from dataclasses import dataclass
from typing import NoReturn

from fastapi import HTTPException

ALLOWED_FIRST_WORDS = {"select", "show", "with"}
# 拦截 SELECT/WITH 中的写入、INTO 和锁定读，其余语法由 MySQL 判断
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
}


@dataclass(frozen=True)
class Token:
    """表示一个参与只读检查的 SQL 词法单元

    Attributes:
        value: 归一化的词法内容，字符串字面量使用占位值
        start: 在输入 SQL 中的字符起始位置，不是字节位置
        quoted: 是否来自字符串或带引用的标识符，不按普通关键字处理
    """

    value: str
    start: int
    quoted: bool = False


def tokens(sql: str, sql_mode: str = "") -> list[Token]:
    """识别 SQL 字符串、标识符、注释与语句分隔符

    Args:
        sql: 待扫描的 SQL 原文
        sql_mode: 实际会话模式，影响反斜杠转义和双引号含义，空字符串使用普通词法规则

    Returns:
        保留位置的词法单元列表，普通注释不产生单元

    Raises:
        HTTPException: 字符串或注释未闭合，或出现可执行注释与优化器 hint
    """
    modes = set(sql_mode.upper().split(","))
    result: list[Token] = []
    i = 0
    while i < len(sql):
        char = sql[i]
        if char.isspace():
            i += 1
            continue
        if char == "#" or (sql.startswith("--", i) and (i + 2 == len(sql) or ord(sql[i + 2]) <= 32)):
            end = re.search(r"[\r\n]", sql[i:])
            i = i + end.start() + 1 if end else len(sql)
            continue
        if sql.startswith("/*", i):
            if sql.startswith(("/*!", "/*+", "/*M!"), i):
                raise_sql_error("Executable SQL comments and optimizer hints are not allowed.")
            end = sql.find("*/", i + 2)
            if end < 0:
                raise_sql_error("Unterminated SQL comment.")
            i = end + 2
            continue
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
            result.append(Token(value, start, quoted=True))
            continue
        if char.isalnum() or char in "_$":
            i += 1
            while i < len(sql) and (sql[i].isalnum() or sql[i] in "_$"):
                i += 1
            result.append(Token(sql[start:i].lower(), start))
            continue
        pair = sql[i : i + 2]
        if pair in {"@@", ":="}:
            result.append(Token(pair, i))
            i += 2
        else:
            result.append(Token(char, i))
            i += 1
    return result


def clean_sql(sql: str, sql_mode: str = "") -> str:
    """检查单条只读 SQL 并移除可选的末尾分号

    Args:
        sql: 调用方提交的 SQL 原文
        sql_mode: 实际会话的 SQL mode，省略时按普通词法规则处理

    Returns:
        去除首尾空白和末尾语句分隔符的 SQL，不重写字段字面量

    Raises:
        HTTPException: SQL 为空、多语句、起始语句不允许或包含被禁止的操作
    """
    cleaned = sql.strip()
    parsed = tokens(cleaned, sql_mode)
    if not parsed:
        raise_sql_error("SQL is empty.")
    if parsed[-1].value == ";" and not parsed[-1].quoted:
        end = parsed.pop().start
        cleaned = cleaned[:end] + cleaned[end + 1 :]
    words = [token.value if not token.quoted else "" for token in parsed]
    if ";" in words:
        raise_sql_error("Only one SQL statement is allowed.")
    if not words or words[0] not in ALLOWED_FIRST_WORDS:
        raise_sql_error("Only SELECT, WITH or SHOW SQL is allowed.")
    for index, token in enumerate(parsed):
        value = token.value
        next_value = words[index + 1] if index + 1 < len(words) else ""
        if not token.quoted and value in {"@", ":="}:
            raise_sql_error("User variables and assignments are not allowed; @@ system reads are allowed.")
        # 带引用的标识符仍可调用原生函数，例如 SELECT `sleep`(1)
        if value in FORBIDDEN_FUNCTIONS and next_value == "(":
            raise_sql_error(f"Function {value.upper()}() is not allowed.")
        if words[0] != "show" and not token.quoted:
            qualified = index > 0 and words[index - 1] == "."
            function = value in READ_FUNCTIONS and next_value == "("
            if value in FORBIDDEN_WORDS and not qualified and not function:
                raise_sql_error(f"Keyword {value.upper()} is not allowed in a read query.")
            if any(tuple(words[index : index + len(phrase)]) == phrase for phrase in LOCKING_PHRASES):
                raise_sql_error("Locking reads are not allowed.")
    return cleaned.strip()


def clean_select_sql(sql: str, sql_mode: str = "") -> str:
    """检查仅适用于 SELECT/WITH 的只读 SQL

    Args:
        sql: 调用方提交的 SQL 原文
        sql_mode: 实际会话的 SQL mode，省略时按普通词法规则处理

    Returns:
        通过检查并移除可选末尾分号的 SQL

    Raises:
        HTTPException: 只读检查失败，或提交了 SHOW 等不适用语句
    """
    cleaned = clean_sql(sql, sql_mode)
    if first_word(cleaned, sql_mode) not in {"select", "with"}:
        raise_sql_error("Only SELECT or WITH SQL is allowed for this operation.")
    return cleaned


def raise_sql_error(detail: str) -> NoReturn:
    """中止请求并报告 SQL 规则错误

    Args:
        detail: 供调用方纠正 SQL 的错误说明

    Raises:
        HTTPException: 始终抛出状态为 400 的异常
    """
    raise HTTPException(status_code=400, detail=detail)


def first_word(sql: str, sql_mode: str = "") -> str:
    """读取跳过普通注释后的首个 SQL 词法单元

    Args:
        sql: 待识别的 SQL
        sql_mode: 实际会话的 SQL mode，省略时按普通词法规则处理

    Returns:
        首个未引用词法单元的归一化内容，无有效单元时为空字符串

    Raises:
        HTTPException: 词法边界不完整或出现禁止的注释
    """
    parsed = tokens(sql, sql_mode)
    return parsed[0].value if parsed and not parsed[0].quoted else ""


def paged_sql(sql: str, limit: int, offset: int) -> str:
    # 分页数值已经过整数校验，直接生成文本可避免驱动再次解释用户 SQL 中的百分号
    """构造多取一行的 SELECT 外层分页查询

    Args:
        sql: 已校验且移除末尾分号的 SELECT/WITH SQL
        limit: 允许返回的正整数行数，实际向数据库请求多一行
        offset: 非负的外层结果偏移量

    Returns:
        保留内层 LIMIT 的 SQL，外层查询不保证继承内层排序

    Raises:
        ValueError: limit 或 offset 不是整数或超出允许范围
    """
    if type(limit) is not int or type(offset) is not int or limit < 1 or offset < 0:
        raise ValueError("Invalid limit or offset.")
    return f"SELECT *\nFROM (\n{sql}\n) AS _codex_query\nLIMIT {limit + 1} OFFSET {offset}"


def count_sql(sql: str) -> str:
    """将 SELECT/WITH 查询包装为结果行数统计

    Args:
        sql: 已校验且移除末尾分号的 SQL，内层 LIMIT 仍然生效

    Returns:
        带 count 列的单行计数 SQL，括号前保留换行以结束末尾行注释
    """
    return f"SELECT COUNT(*) AS count FROM (\n{sql}\n) AS _count_query"


def explain_sql(sql: str) -> str:
    """为已校验的查询生成原生执行计划语句

    Args:
        sql: 已校验且移除末尾分号的 SELECT/WITH SQL

    Returns:
        以 EXPLAIN 为前缀的 SQL
    """
    return f"EXPLAIN {sql}"
