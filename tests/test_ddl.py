import unittest

from app.ddl import render_table_ddl, render_view_ddl


class DdlTest(unittest.TestCase):
    def test_table_ddl_keeps_primary_not_null_and_foreign_key(self) -> None:
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
