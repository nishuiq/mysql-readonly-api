import re
from dataclasses import dataclass
from typing import NoReturn

from fastapi import HTTPException

ALLOWED_FIRST_WORDS = {"select", "show", "with"}
# SELECT/WITH cannot contain DML, INTO, or locking reads. Other syntax is MySQL's job.
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
    value: str
    start: int
    quoted: bool = False


def tokens(sql: str, sql_mode: str = "") -> list[Token]:
    """Tokenize boundaries only; leave SQL grammar and version support to MySQL."""
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
        # Quoted identifiers can still call native functions, e.g. SELECT `sleep`(1).
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
    cleaned = clean_sql(sql, sql_mode)
    if first_word(cleaned, sql_mode) not in {"select", "with"}:
        raise_sql_error("Only SELECT or WITH SQL is allowed for this operation.")
    return cleaned


def raise_sql_error(detail: str) -> NoReturn:
    raise HTTPException(status_code=400, detail=detail)


def first_word(sql: str, sql_mode: str = "") -> str:
    parsed = tokens(sql, sql_mode)
    return parsed[0].value if parsed and not parsed[0].quoted else ""


def paged_sql(sql: str, limit: int, offset: int) -> str:
    # These are validated integers, not user SQL or DBAPI bind parameters.
    if type(limit) is not int or type(offset) is not int or limit < 1 or offset < 0:
        raise ValueError("Invalid limit or offset.")
    return f"SELECT *\nFROM (\n{sql}\n) AS _codex_query\nLIMIT {limit + 1} OFFSET {offset}"


def count_sql(sql: str) -> str:
    return f"SELECT COUNT(*) AS count FROM (\n{sql}\n) AS _count_query"


def explain_sql(sql: str) -> str:
    return f"EXPLAIN {sql}"
