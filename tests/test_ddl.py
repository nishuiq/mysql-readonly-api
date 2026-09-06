"""覆盖 DDL 字面量、对象引用与版本元数据差异"""

import unittest
from unittest.mock import MagicMock, Mock, patch

import pymysql
from fastapi import HTTPException
from sqlalchemy.exc import ProgrammingError

from app.ddl import (
    column_type,
    ddl_ident,
    default_sql,
    on_update_sql,
    render_table_ddl,
    render_view_ddl,
    show_create_view,
    sql_string,
    table_checks,
    table_indexes,
)
from app.table_params import parse_table_names


class DdlTest(unittest.TestCase):
    """覆盖 DDL 字面量、对象引用与版本元数据差异"""

    def test_string_defaults_are_not_guessed_as_sql_expressions(self):
        """字符串默认值保持字符串含义且引用遵循 SQL mode"""
        for value in ["NULL", "CURRENT_TIMESTAMP", "UUID()", "NOW()", "a'b\\c"]:
            column = {"column_default": value, "data_type": "varchar", "extra": ""}
            self.assertEqual(default_sql(column), sql_string(value))
        self.assertEqual(default_sql({"column_default": None, "data_type": "varchar"}), "")
        self.assertEqual(
            default_sql({"column_default": "CURRENT_TIMESTAMP(6)", "data_type": "timestamp"}), "CURRENT_TIMESTAMP(6)"
        )
        self.assertEqual(
            default_sql({"column_default": "uuid()", "data_type": "varchar", "extra": "DEFAULT_GENERATED"}), "(uuid())"
        )
        self.assertEqual(sql_string("a'b\\c", no_backslash=True), "'a''b\\c'")
        self.assertEqual(
            on_update_sql("DEFAULT_GENERATED on update CURRENT_TIMESTAMP(6) INVISIBLE"),
            "on update CURRENT_TIMESTAMP(6)",
        )

    def test_identifier_and_type_formatting_preserves_literals(self):
        """标识符正确引用且类型排版不改写枚举值"""
        for value in ["enum('x,1','int(11)')", "set('a,2')", "int(5) unsigned zerofill"]:
            self.assertEqual(column_type({"column_type": value}), value)
        self.assertEqual(column_type({"column_type": "decimal(10,2)"}), "decimal(10, 2)")
        self.assertEqual(ddl_ident("select"), "`select`")
        self.assertEqual(ddl_ident("a`b:100%"), "`a``b:100%`")

    def test_mysql_57_never_requests_mysql_8_catalog_fields(self):
        """MySQL 5.7 的元数据查询不引用 8.x 专属字段"""
        session = Mock(info={"mysql_version": (5, 7, 44)})
        with patch("app.ddl.fetch_rows", return_value=[]) as fetch:
            table_indexes(session, "app", ["table"])
            sql = fetch.call_args.args[1]
            self.assertIn("NULL AS expression", sql)
            self.assertIn("'YES' AS is_visible", sql)
            self.assertNotIn("EXPRESSION", sql)
            self.assertNotIn("IS_VISIBLE", sql)
            fetch.reset_mock()
            self.assertEqual(table_checks(session, "app", ["table"]), {})
            fetch.assert_not_called()

    def test_view_fallback_is_only_for_permission_errors(self):
        """视图源码只在权限不足时降级"""
        session = MagicMock()
        execute = session.connection.return_value.exec_driver_sql
        for number in [1142, 1064, 2013]:
            error = ProgrammingError("", {}, pymysql.err.ProgrammingError(number, "driver message"))
            execute.side_effect = error
            if number == 1142:
                self.assertEqual(show_create_view(session, "app", "view"), "")
            else:
                with self.assertRaises(ProgrammingError):
                    show_create_view(session, "app", "view")

    def test_table_parameters_keep_quoted_names_and_deduplicate(self):
        """对象参数保留引用内的字符并按请求顺序去重"""
        self.assertEqual(
            parse_table_names(["a,b", "a", "`a,b`,`a``b`,` spaced `"]), ["a", "b", "a,b", "a`b", " spaced "]
        )
        for value in ["`missing", "`a`oops"]:
            with self.assertRaises(HTTPException):
                parse_table_names([value])

    def test_table_ddl_keeps_primary_not_null_and_foreign_key(self) -> None:
        """表摘要保留非空主键、外键和表属性"""
        table_meta = {
            "table_comment": "Example",
            "charset": "utf8mb4",
            "table_collation": "utf8mb4_general_ci",
            "engine": "InnoDB",
        }
        columns = [
            {
                "column_name": "id",
                "column_type": "int(11)",
                "data_type": "int",
                "is_nullable": "NO",
                "column_default": None,
                "extra": "auto_increment",
                "column_comment": "Primary key",
                "generation_expression": "",
            },
            {
                "column_name": "parent_id",
                "column_type": "int(11)",
                "data_type": "int",
                "is_nullable": "YES",
                "column_default": None,
                "extra": "",
                "column_comment": "",
                "generation_expression": "",
            },
        ]
        indexes = {
            "PRIMARY": [
                {
                    "seq_in_index": 1,
                    "column_name": "id",
                    "sub_part": None,
                    "non_unique": 0,
                    "index_type": "BTREE",
                }
            ]
        }
        foreign_keys = {
            "fk_example_parent": [
                {
                    "ordinal_position": 1,
                    "column_name": "parent_id",
                    "referenced_table_schema": "example_app",
                    "referenced_table_name": "parent",
                    "referenced_column_name": "id",
                    "update_rule": "CASCADE",
                    "delete_rule": "RESTRICT",
                }
            ]
        }

        ddl = render_table_ddl(
            table="example",
            table_meta=table_meta,
            columns=columns,
            indexes=indexes,
            foreign_keys=foreign_keys,
        )

        self.assertIn("id        int auto_increment not null", ddl)
        self.assertIn("foreign key (parent_id)", ddl)
        self.assertIn("references example_app.parent (id)", ddl)
        self.assertIn("engine = InnoDB", ddl)
        self.assertIn("collate = utf8mb4_general_ci", ddl)

    def test_view_ddl_returns_source_when_visible(self) -> None:
        """可见视图使用原生源码并补齐分号"""
        ddl = render_view_ddl(
            table="example_view",
            create_sql="CREATE DEFINER=`root`@`%` VIEW `example_view` AS select 1 AS `id`",
            columns=[],
        )

        self.assertEqual(
            ddl,
            "CREATE DEFINER=`root`@`%` VIEW `example_view` AS select 1 AS `id`;",
        )

    def test_view_ddl_marks_missing_source(self) -> None:
        """不可见视图明确标记源码缺失并展示可见列注释"""
        ddl = render_view_ddl(
            table="example_view",
            create_sql="",
            columns=[{"column_name": "id", "column_comment": "Identifier"}],
        )

        self.assertIn("create view example_view as", ddl)
        self.assertIn("/* missing source code */", ddl)
        self.assertIn("comment on column example_view.id not supported: Identifier", ddl)


if __name__ == "__main__":
    unittest.main()
