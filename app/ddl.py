from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import HTTPException
from sqlalchemy.dialects.mysql import dialect
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, text

from app.errors import mysql_error_number
from app.table_params import parse_table_names

# Render literal SQL, without the DBAPI percent-escaping used by format/pyformat.
IDENTIFIER_PREPARER = dialect(paramstyle="named").identifier_preparer
INTEGER_DISPLAY_WIDTH = re.compile(r"^(tinyint|smallint|mediumint|int|integer|bigint)\(\d+\)", re.IGNORECASE)
STRING_DEFAULT_TYPES = {
    "char",
    "varchar",
    "binary",
    "varbinary",
    "blob",
    "text",
    "tinyblob",
    "tinytext",
    "mediumblob",
    "mediumtext",
    "longblob",
    "longtext",
    "enum",
    "set",
    "date",
    "datetime",
    "time",
    "timestamp",
}


def table_ddl_text(session: Session, schema: str, table: Sequence[str]) -> str:
    """批量读取紧凑 DDL；版本分支只影响元数据字段，不重写用户 SQL。"""
    names = parse_table_names(table)
    if not names:
        raise HTTPException(422, "query.table: provide at least one table name.")
    table_meta = table_metadata(session, schema, names)
    missing = [name for name in names if name not in table_meta]
    if missing:
        raise HTTPException(404, f"Object not found or not visible: {schema}.{', '.join(missing)}")
    columns = table_columns(session, schema, names)
    indexes = table_indexes(session, schema, names)
    foreign_keys = table_foreign_keys(session, schema, names)
    checks = table_checks(session, schema, names)
    no_backslash = "NO_BACKSLASH_ESCAPES" in session.info["sql_mode"].upper().split(",")
    definitions = []
    for name in names:
        metadata = table_meta[name]
        if str(metadata.get("table_type") or "").upper() == "VIEW":
            definitions.append(render_view_ddl(name, show_create_view(session, schema, name), columns.get(name, [])))
        else:
            definitions.append(
                render_table_ddl(
                    name,
                    metadata,
                    columns.get(name, []),
                    indexes.get(name, {}),
                    foreign_keys.get(name, {}),
                    checks.get(name, []),
                    no_backslash,
                )
            )
    return "\n\n".join(definitions)


def render_table_ddl(
    table: str,
    table_meta: Mapping[str, Any],
    columns: Sequence[Mapping[str, Any]],
    indexes: Mapping[str, Sequence[Mapping[str, Any]]],
    foreign_keys: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    checks: Sequence[Mapping[str, Any]] = (),
    no_backslash: bool = False,
) -> str:
    """生成单表 DDL 文本。"""
    primary_columns = index_columns(indexes.get("PRIMARY", []))

    inline_primary = (
        len(primary_columns) == 1
        and any(ddl_ident(str(column["column_name"])) == primary_columns[0] for column in columns)
        and not index_options(indexes.get("PRIMARY", []), no_backslash)
    )
    body_items = column_items(columns, primary_columns if inline_primary else [], table_meta, no_backslash)
    if primary_columns and not inline_primary:
        body_items.append(
            f"    primary key ({column_list(primary_columns)})" + index_options(indexes["PRIMARY"], no_backslash)
        )
    body_items.extend(unique_key_items(indexes, no_backslash))
    body_items.extend(foreign_key_items(foreign_keys or {}))
    for check in checks:
        enforcement = " not enforced" if check.get("enforced") == "NO" else ""
        body_items.append(
            f"    constraint {ddl_ident(str(check['constraint_name']))} check ({check['check_clause']}){enforcement}"
        )

    lines = [f"create table {ddl_ident(table)}", "("]
    for index, item in enumerate(body_items):
        suffix = "," if index < len(body_items) - 1 else ""
        lines.append(f"{item}{suffix}")
    lines.append(table_suffix(table_meta, no_backslash))
    lines.extend(index_items(table, indexes, no_backslash))
    if table_meta.get("create_options"):
        lines.append("-- Additional table options omitted; use SHOW CREATE TABLE for the complete definition.")
    return "\n".join(lines)


def render_view_ddl(
    table: str,
    create_sql: str,
    columns: Sequence[Mapping[str, Any]],
) -> str:
    """生成 IDEA 风格 View DDL；源码不可见时显式输出占位。"""
    if create_sql:
        normalized = create_sql.rstrip()
        return normalized if normalized.endswith(";") else normalized + ";"

    lines = [f"create view {ddl_ident(table)} as", "/* missing source code */", ";"]
    for column in columns:
        comment = str(column.get("column_comment") or "")
        if not comment:
            continue
        safe_comment = comment.replace("\r", "\\r").replace("\n", "\\n").replace("*/", "* /")
        lines.extend(
            [
                "",
                (
                    f"/* comment on column {ddl_ident(table)}.{ddl_ident(str(column['column_name']))} "
                    f"not supported: {safe_comment} */"
                ),
            ]
        )
    return "\n".join(lines)


def table_metadata(session: Session, schema: str, table_names: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    """批量读取对象类型、表属性、注释和字符集。"""
    table_filter, params = table_filter_params(schema, table_names)
    rows = fetch_rows(
        session,
        f"""
        SELECT
            t.TABLE_NAME AS table_name,
            t.TABLE_TYPE AS table_type,
            t.ENGINE AS engine,
            t.TABLE_COLLATION AS table_collation,
            t.TABLE_COMMENT AS table_comment,
            t.CREATE_OPTIONS AS create_options,
            c.CHARACTER_SET_NAME AS charset
        FROM information_schema.TABLES t
        LEFT JOIN information_schema.COLLATION_CHARACTER_SET_APPLICABILITY c
          ON c.COLLATION_NAME = t.TABLE_COLLATION
        WHERE t.TABLE_SCHEMA = :schema
          AND t.TABLE_NAME IN ({table_filter})
        """,
        params,
    )
    return {str(row["table_name"]): row for row in rows}


def table_columns(session: Session, schema: str, table_names: Sequence[str]) -> dict[str, list[Mapping[str, Any]]]:
    """批量读取字段定义。"""
    table_filter, params = table_filter_params(schema, table_names)
    rows = fetch_rows(
        session,
        f"""
        SELECT
            TABLE_NAME AS table_name,
            COLUMN_NAME AS column_name,
            COLUMN_TYPE AS column_type,
            DATA_TYPE AS data_type,
            IS_NULLABLE AS is_nullable,
            COLUMN_DEFAULT AS column_default,
            EXTRA AS extra,
            COLUMN_COMMENT AS column_comment,
            GENERATION_EXPRESSION AS generation_expression,
            CHARACTER_SET_NAME AS character_set_name,
            COLLATION_NAME AS collation_name
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = :schema
          AND TABLE_NAME IN ({table_filter})
        ORDER BY TABLE_NAME, ORDINAL_POSITION
        """,
        params,
    )
    columns: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        columns.setdefault(str(row["table_name"]), []).append(row)
    return columns


def table_indexes(
    session: Session,
    schema: str,
    table_names: Sequence[str],
) -> dict[str, dict[str, list[Mapping[str, Any]]]]:
    """批量读取索引定义并按表名、索引名称分组。"""
    table_filter, params = table_filter_params(schema, table_names)
    version = session.info["mysql_version"]
    expression = "EXPRESSION" if version >= (8, 0, 13) else "NULL"
    visible = "IS_VISIBLE" if version >= (8, 0, 0) else "'YES'"
    rows = fetch_rows(
        session,
        f"""
        SELECT
            TABLE_NAME AS table_name,
            INDEX_NAME AS index_name,
            NON_UNIQUE AS non_unique,
            SEQ_IN_INDEX AS seq_in_index,
            COLUMN_NAME AS column_name,
            SUB_PART AS sub_part,
            INDEX_TYPE AS index_type,
            COLLATION AS collation,
            INDEX_COMMENT AS index_comment,
            {expression} AS expression,
            {visible} AS is_visible
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = :schema
          AND TABLE_NAME IN ({table_filter})
        ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
        """,
        params,
    )
    indexes: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    for row in rows:
        indexes_for_table = indexes.setdefault(str(row["table_name"]), {})
        indexes_for_table.setdefault(str(row["index_name"]), []).append(row)
    return indexes


def table_foreign_keys(
    session: Session,
    schema: str,
    table_names: Sequence[str],
) -> dict[str, dict[str, list[Mapping[str, Any]]]]:
    """批量读取外键定义并按表名、约束名称分组。"""
    table_filter, params = table_filter_params(schema, table_names)
    rows = fetch_rows(
        session,
        f"""
        SELECT
            k.TABLE_NAME AS table_name,
            k.CONSTRAINT_NAME AS constraint_name,
            k.ORDINAL_POSITION AS ordinal_position,
            k.COLUMN_NAME AS column_name,
            k.REFERENCED_TABLE_SCHEMA AS referenced_table_schema,
            k.REFERENCED_TABLE_NAME AS referenced_table_name,
            k.REFERENCED_COLUMN_NAME AS referenced_column_name,
            r.UPDATE_RULE AS update_rule,
            r.DELETE_RULE AS delete_rule
        FROM information_schema.KEY_COLUMN_USAGE k
        JOIN information_schema.REFERENTIAL_CONSTRAINTS r
          ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA
         AND r.TABLE_NAME = k.TABLE_NAME
         AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME
        WHERE k.TABLE_SCHEMA = :schema
          AND k.TABLE_NAME IN ({table_filter})
          AND k.REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY k.TABLE_NAME, k.CONSTRAINT_NAME, k.ORDINAL_POSITION
        """,
        params,
    )
    foreign_keys: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    for row in rows:
        keys_for_table = foreign_keys.setdefault(str(row["table_name"]), {})
        keys_for_table.setdefault(str(row["constraint_name"]), []).append(row)
    return foreign_keys


def table_checks(
    session: Session,
    schema: str,
    table_names: Sequence[str],
) -> dict[str, list[Mapping[str, Any]]]:
    # 5.7 parses but does not enforce/store CHECK constraints; the catalog is 8.0.16+.
    if session.info["mysql_version"] < (8, 0, 16):
        return {}
    table_filter, params = table_filter_params(schema, table_names)
    rows = fetch_rows(
        session,
        f"""
        SELECT t.TABLE_NAME AS table_name, t.CONSTRAINT_NAME AS constraint_name,
               c.CHECK_CLAUSE AS check_clause, t.ENFORCED AS enforced
        FROM information_schema.TABLE_CONSTRAINTS t
        JOIN information_schema.CHECK_CONSTRAINTS c
          ON c.CONSTRAINT_SCHEMA = t.CONSTRAINT_SCHEMA AND c.CONSTRAINT_NAME = t.CONSTRAINT_NAME
        WHERE t.CONSTRAINT_SCHEMA = :schema AND t.TABLE_NAME IN ({table_filter})
          AND t.CONSTRAINT_TYPE = 'CHECK'
        ORDER BY t.TABLE_NAME, t.CONSTRAINT_NAME
    """,
        params,
    )
    checks: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        checks.setdefault(str(row["table_name"]), []).append(row)
    return checks


def show_create_view(session: Session, schema: str, table: str) -> str:
    """仅权限不足时降级；连接、语法、失效视图等异常正常反馈。"""
    name = f"{IDENTIFIER_PREPARER.quote_identifier(schema)}.{IDENTIFIER_PREPARER.quote_identifier(table)}"
    try:
        with session.connection().exec_driver_sql(
            f"SHOW CREATE VIEW {name}",
            execution_options={"no_parameters": True},
        ) as result:
            row = result.fetchone()
    except SQLAlchemyError as exc:
        if mysql_error_number(exc) in {1142, 1143, 1227}:
            return ""
        raise
    if row is None:
        return ""
    value = row._mapping.get("Create View")
    return str(value) if value is not None else ""


def fetch_rows(session: Session, sql: str, params: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """执行元数据查询并返回字典行。"""
    with session.exec(text(sql), params=params) as result:
        return [dict(row._mapping) for row in result.fetchall()]


def table_filter_params(schema: str, table_names: Sequence[str]) -> tuple[str, dict[str, Any]]:
    """生成批量表名过滤条件参数。"""
    params: dict[str, Any] = {"schema": schema}
    placeholders: list[str] = []
    for index, table_name in enumerate(table_names):
        key = f"table_{index}"
        params[key] = table_name
        placeholders.append(f":{key}")
    return ", ".join(placeholders), params


def column_items(
    columns: Sequence[Mapping[str, Any]],
    primary_columns: Sequence[str],
    table_meta: Mapping[str, Any],
    no_backslash: bool,
) -> list[str]:
    """生成字段 DDL 行。"""
    name_width = max((len(ddl_ident(str(column["column_name"]))) for column in columns), default=0)
    type_width = max((len(column_type(column)) for column in columns), default=0)
    single_primary = len(primary_columns) == 1
    items: list[str] = []
    for column in columns:
        column_name = str(column["column_name"])
        parts = column_parts(column, table_meta, no_backslash)
        line = f"    {ddl_ident(column_name).ljust(name_width)} {column_type(column).ljust(type_width)}"
        if parts:
            line = f"{line} {' '.join(parts)}"
        if single_primary and ddl_ident(column_name) == primary_columns[0]:
            line = f"{line}\n        primary key"
        items.append(line.rstrip())
    return items


def column_parts(column: Mapping[str, Any], table_meta: Mapping[str, Any], no_backslash: bool) -> list[str]:
    """生成字段类型后面的属性片段。"""
    parts: list[str] = []
    extra = str(column["extra"] or "")
    extra_lower = extra.lower()
    generated_expression = str(column["generation_expression"] or "")

    charset = column.get("character_set_name")
    collation = column.get("collation_name")
    if charset and charset != table_meta.get("charset"):
        parts.append(f"character set {ddl_ident(str(charset))}")
    if collation and collation != table_meta.get("table_collation"):
        parts.append(f"collate {ddl_ident(str(collation))}")
    if generated_expression:
        storage = "stored" if "stored generated" in extra_lower else "virtual"
        parts.append(f"as ({generated_expression}) {storage}")
    if "auto_increment" in extra_lower:
        parts.append("auto_increment")

    default = default_sql(column, no_backslash)
    if default:
        parts.append(f"default {default}")

    parts.append("null" if column["is_nullable"] == "YES" else "not null")

    on_update = on_update_sql(extra)
    if on_update:
        parts.append(on_update)

    if "invisible" in extra_lower:
        parts.append("invisible")
    comment = str(column["column_comment"] or "")
    if comment:
        parts.append(f"comment {sql_string(comment, no_backslash)}")
    return parts


def unique_key_items(indexes: Mapping[str, Sequence[Mapping[str, Any]]], no_backslash: bool) -> list[str]:
    """生成唯一索引约束 DDL。"""
    items: list[str] = []
    for index_name, index_rows in sorted(indexes.items()):
        if index_name == "PRIMARY" or not index_rows or int(index_rows[0]["non_unique"]) != 0:
            continue
        items.append(
            f"    constraint {ddl_ident(index_name)}\n        unique ({column_list(index_columns(index_rows))})"
            + index_options(index_rows, no_backslash)
        )
    return items


def foreign_key_items(
    foreign_keys: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[str]:
    """生成外键约束 DDL。"""
    items: list[str] = []
    for constraint_name, key_rows in sorted(foreign_keys.items()):
        if not key_rows:
            continue
        rows = sorted(key_rows, key=lambda row: int(row["ordinal_position"]))
        first = rows[0]
        local_columns = column_list([ddl_ident(str(row["column_name"])) for row in rows])
        referenced_columns = column_list([ddl_ident(str(row["referenced_column_name"])) for row in rows])
        referenced_table = (
            f"{ddl_ident(str(first['referenced_table_schema']))}.{ddl_ident(str(first['referenced_table_name']))}"
        )
        item = (
            f"    constraint {ddl_ident(constraint_name)}\n"
            f"        foreign key ({local_columns}) references {referenced_table} ({referenced_columns})"
        )
        update_rule = str(first.get("update_rule") or "")
        delete_rule = str(first.get("delete_rule") or "")
        if update_rule:
            item += f"\n            on update {update_rule.lower()}"
        if delete_rule:
            item += f"\n            on delete {delete_rule.lower()}"
        items.append(item)
    return items


def index_items(
    table: str,
    indexes: Mapping[str, Sequence[Mapping[str, Any]]],
    no_backslash: bool,
) -> list[str]:
    """生成普通索引 DDL。"""
    items: list[str] = []
    for index_name, index_rows in sorted(indexes.items()):
        if index_name == "PRIMARY" or not index_rows or int(index_rows[0]["non_unique"]) == 0:
            continue
        index_type = str(index_rows[0]["index_type"] or "").lower()
        prefix = "create"
        if index_type in {"fulltext", "spatial"}:
            prefix = f"{prefix} {index_type}"
        items.append(
            "\n".join(
                [
                    "",
                    f"{prefix} index {ddl_ident(index_name)}",
                    f"    on {ddl_ident(table)} ({column_list(index_columns(index_rows))})"
                    f"{index_options(index_rows, no_backslash)};",
                ]
            )
        )
    return items


def table_suffix(table_meta: Mapping[str, Any], no_backslash: bool) -> str:
    """生成 create table 结尾的表属性。"""
    options: list[str] = []
    engine = str(table_meta.get("engine") or "")
    table_comment = str(table_meta.get("table_comment") or "")
    charset = str(table_meta.get("charset") or "")
    table_collation = str(table_meta.get("table_collation") or "")
    if engine:
        options.append(f"engine = {engine}")
    if charset:
        options.append(f"charset = {charset}")
    if table_collation:
        options.append(f"collate = {table_collation}")
    if table_comment:
        options.append(f"comment {sql_string(table_comment, no_backslash)}")
    if not options:
        return ");"
    return ")\n    " + " ".join(options) + ";"


def index_columns(index_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """按索引顺序读取索引字段。"""
    rows = sorted(index_rows, key=lambda row: int(row["seq_in_index"]))
    columns: list[str] = []
    for row in rows:
        expression = row.get("expression")
        column = f"({expression})" if expression is not None else ddl_ident(str(row["column_name"]))
        if row["sub_part"] is not None:
            column = f"{column}({row['sub_part']})"
        if row.get("collation") == "D":
            column += " desc"
        columns.append(column)
    return columns


def column_list(columns: Sequence[str]) -> str:
    """生成逗号分隔字段列表。"""
    return ", ".join(columns)


def index_options(rows: Sequence[Mapping[str, Any]], no_backslash: bool) -> str:
    if not rows:
        return ""
    first = rows[0]
    options = []
    if str(first.get("index_type") or "").upper() == "HASH":
        options.append("using hash")
    if first.get("is_visible") == "NO":
        options.append("invisible")
    if first.get("index_comment"):
        options.append(f"comment {sql_string(str(first['index_comment']), no_backslash)}")
    return " " + " ".join(options) if options else ""


def default_sql(column: Mapping[str, Any], no_backslash: bool = False) -> str:
    value = column["column_default"]
    if value is None:
        return ""
    if isinstance(value, bytes):
        return "0x" + value.hex()
    text_value = str(value)
    data_type = str(column["data_type"]).lower()
    if data_type in {"datetime", "timestamp"} and re.fullmatch(r"CURRENT_TIMESTAMP(?:\(\d*\))?", text_value, re.I):
        return text_value
    if "default_generated" in str(column.get("extra") or "").lower():
        return f"({text_value})"
    if data_type in STRING_DEFAULT_TYPES or data_type == "json":
        return sql_string(text_value, no_backslash)
    return text_value


def column_type(column: Mapping[str, Any]) -> str:
    value = str(column["column_type"])
    if "zerofill" not in value.lower():
        value = INTEGER_DISPLAY_WIDTH.sub(lambda match: match.group(1), value)
    # Spacing only in numeric precision, never inside enum/set string literals.
    if re.fullmatch(r"(?:decimal|numeric|float|double)\(\d+,\d+\)(?: unsigned)?(?: zerofill)?", value, re.I):
        value = value.replace(",", ", ")
    return value


def on_update_sql(extra: str) -> str:
    match = re.search(r"on update CURRENT_TIMESTAMP(?:\(\d*\))?", extra, re.I)
    return match.group(0) if match else ""


def ddl_ident(value: str) -> str:
    return IDENTIFIER_PREPARER.quote(value)


def sql_string(value: str, no_backslash: bool = False) -> str:
    if not no_backslash:
        value = value.replace("\\", "\\\\")
    return "'" + value.replace("'", "''") + "'"
