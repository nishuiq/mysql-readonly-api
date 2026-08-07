from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from sqlmodel import Session, text

from app.database import db_session
from app.table_params import parse_table_names

SIMPLE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
INTEGER_DISPLAY_WIDTH = re.compile(r"\b(tinyint|smallint|mediumint|int|integer|bigint)\(\d+\)", re.IGNORECASE)
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
FUNCTION_DEFAULT_PREFIXES = (
    "CURRENT_TIMESTAMP",
    "CURRENT_DATE",
    "CURRENT_TIME",
    "LOCALTIME",
    "LOCALTIMESTAMP",
    "NOW(",
    "UUID(",
)


def table_ddl_text(profile: str, schema: str, table: Sequence[str]) -> str:
    """生成一个或多个表的 IDEA 风格 DDL。"""
    table_names = parse_table_names(table)
    unique_names = unique_table_names(table_names)
    if not unique_names:
        return ""
    with db_session(profile) as session:
        table_meta = table_metadata(session, schema, unique_names)
        columns = table_columns(session, schema, unique_names)
        indexes = table_indexes(session, schema, unique_names)
        return "\n\n".join(
            render_table_ddl(
                table=table_name,
                table_meta=table_meta[table_name],
                columns=columns.get(table_name, []),
                indexes=indexes.get(table_name, {}),
            )
            for table_name in table_names
            if table_name in table_meta
        )


def render_table_ddl(
    table: str,
    table_meta: Mapping[str, Any],
    columns: Sequence[Mapping[str, Any]],
    indexes: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str:
    """生成单表 DDL 文本。"""
    primary_columns = index_columns(indexes.get("PRIMARY", []))

    body_items = column_items(columns, primary_columns)
    body_items.extend(primary_key_items(primary_columns))
    body_items.extend(unique_key_items(indexes))

    lines = [f"create table {ddl_ident(table)}", "("]
    for index, item in enumerate(body_items):
        suffix = "," if index < len(body_items) - 1 else ""
        lines.append(f"{item}{suffix}")
    lines.append(table_suffix(table_meta))
    lines.extend(index_items(table, indexes))
    return "\n".join(lines)


def table_metadata(session: Session, schema: str, table_names: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    """批量读取表注释和字符集。"""
    table_filter, params = table_filter_params(schema, table_names)
    rows = fetch_rows(
        session,
        f"""
        SELECT
            t.TABLE_NAME AS table_name,
            t.TABLE_COMMENT AS table_comment,
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
            GENERATION_EXPRESSION AS generation_expression
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
            INDEX_TYPE AS index_type
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


def fetch_rows(session: Session, sql: str, params: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """执行元数据查询并返回字典行。"""
    result = session.exec(text(sql), params=params)
    return [dict(row._mapping) for row in result.fetchall()]


def unique_table_names(table_names: Sequence[str]) -> list[str]:
    """按请求顺序去重表名，用于批量读取元数据。"""
    return list(dict.fromkeys(table_names))


def table_filter_params(schema: str, table_names: Sequence[str]) -> tuple[str, dict[str, Any]]:
    """生成批量表名过滤条件参数。"""
    params: dict[str, Any] = {"schema": schema}
    placeholders: list[str] = []
    for index, table_name in enumerate(table_names):
        key = f"table_{index}"
        params[key] = table_name
        placeholders.append(f":{key}")
    return ", ".join(placeholders), params


def column_items(columns: Sequence[Mapping[str, Any]], primary_columns: Sequence[str]) -> list[str]:
    """生成字段 DDL 行。"""
    name_width = max((len(ddl_ident(str(column["column_name"]))) for column in columns), default=0)
    type_width = max((len(column_type(column)) for column in columns), default=0)
    single_primary = len(primary_columns) == 1
    items: list[str] = []
    for column in columns:
        column_name = str(column["column_name"])
        parts = column_parts(column, is_primary=column_name in primary_columns)
        line = f"    {ddl_ident(column_name).ljust(name_width)} {column_type(column).ljust(type_width)}"
        if parts:
            line = f"{line} {' '.join(parts)}"
        if single_primary and column_name == primary_columns[0]:
            line = f"{line}\n        primary key"
        items.append(line.rstrip())
    return items


def column_parts(column: Mapping[str, Any], is_primary: bool) -> list[str]:
    """生成字段类型后面的属性片段。"""
    parts: list[str] = []
    extra = str(column["extra"] or "")
    extra_lower = extra.lower()
    generated_expression = str(column["generation_expression"] or "")

    if generated_expression:
        parts.append(f"as ({generated_expression})")
    if "auto_increment" in extra_lower:
        parts.append("auto_increment")

    default = default_sql(column)
    if default:
        parts.append(f"default {default}")

    if not is_primary:
        parts.append("null" if column["is_nullable"] == "YES" else "not null")

    on_update = on_update_sql(extra)
    if on_update:
        parts.append(on_update)

    comment = str(column["column_comment"] or "")
    if comment:
        parts.append(f"comment {sql_string(comment)}")
    return parts


def primary_key_items(primary_columns: Sequence[str]) -> list[str]:
    """生成复合主键 DDL；单字段主键写在字段行下方。"""
    if len(primary_columns) <= 1:
        return []
    return [f"    primary key ({column_list(primary_columns)})"]


def unique_key_items(indexes: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[str]:
    """生成唯一索引约束 DDL。"""
    items: list[str] = []
    for index_name, index_rows in sorted(indexes.items()):
        if index_name == "PRIMARY" or not index_rows or int(index_rows[0]["non_unique"]) != 0:
            continue
        items.append(
            f"    constraint {ddl_ident(index_name)}\n        unique ({column_list(index_columns(index_rows))})"
        )
    return items


def index_items(table: str, indexes: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[str]:
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
                    f"    on {ddl_ident(table)} ({column_list(index_columns(index_rows))});",
                ]
            )
        )
    return items


def table_suffix(table_meta: Mapping[str, Any]) -> str:
    """生成 create table 结尾的表属性。"""
    options: list[str] = []
    table_comment = str(table_meta.get("table_comment") or "")
    charset = str(table_meta.get("charset") or "")
    if table_comment:
        options.append(f"comment {sql_string(table_comment)}")
    if charset:
        options.append(f"charset = {charset}")
    if not options:
        return ");"
    return ")\n    " + " ".join(options) + ";"


def index_columns(index_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """按索引顺序读取索引字段。"""
    rows = sorted(index_rows, key=lambda row: int(row["seq_in_index"]))
    columns: list[str] = []
    for row in rows:
        column = ddl_ident(str(row["column_name"]))
        if row["sub_part"] is not None:
            column = f"{column}({row['sub_part']})"
        columns.append(column)
    return columns


def column_list(columns: Sequence[str]) -> str:
    """生成逗号分隔字段列表。"""
    return ", ".join(columns)


def default_sql(column: Mapping[str, Any]) -> str:
    """生成字段默认值 DDL。"""
    value = column["column_default"]
    if value is None:
        return ""
    text_value = str(value)
    if text_value.upper() == "NULL":
        return "NULL"
    if is_function_default(text_value):
        return text_value
    if str(column["data_type"]).lower() in STRING_DEFAULT_TYPES:
        return sql_string(text_value)
    return text_value


def column_type(column: Mapping[str, Any]) -> str:
    """生成更接近 IDEA 展示风格的字段类型。"""
    value = str(column["column_type"])
    value = INTEGER_DISPLAY_WIDTH.sub(lambda match: match.group(1), value)
    return re.sub(r",(?=\d)", ", ", value)


def is_function_default(value: str) -> bool:
    """判断默认值是否是数据库函数。"""
    upper_value = value.upper()
    return upper_value.startswith(FUNCTION_DEFAULT_PREFIXES)


def on_update_sql(extra: str) -> str:
    """从 EXTRA 中提取 on update 片段。"""
    extra_lower = extra.lower()
    index = extra_lower.find("on update")
    if index < 0:
        return ""
    return extra[index:]


def ddl_ident(value: str) -> str:
    """生成 DDL 标识符，普通命名不加反引号。"""
    if SIMPLE_IDENT.match(value):
        return value
    return "`" + value.replace("`", "``") + "`"


def sql_string(value: str) -> str:
    """生成 SQL 字符串字面量。"""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"
