import importlib.util
import unittest
from pathlib import Path

from fastapi import HTTPException

SQL_GUARD_PATH = Path(__file__).resolve().parents[1] / "app" / "sql_guard.py"
SQL_GUARD_SPEC = importlib.util.spec_from_file_location("sql_guard", SQL_GUARD_PATH)
if SQL_GUARD_SPEC is None or SQL_GUARD_SPEC.loader is None:
    raise RuntimeError(f"Cannot load SQL guard module: {SQL_GUARD_PATH}")
sql_guard = importlib.util.module_from_spec(SQL_GUARD_SPEC)
SQL_GUARD_SPEC.loader.exec_module(sql_guard)
clean_sql = sql_guard.clean_sql
clean_select_sql = sql_guard.clean_select_sql
explain_sql = sql_guard.explain_sql


class SqlGuardTest(unittest.TestCase):
    def assert_rejected(self, sql: str) -> None:
        with self.assertRaises(HTTPException):
            clean_sql(sql)

    def test_allows_plain_select(self) -> None:
        self.assertEqual(clean_sql("select * from example_app.orders"), "select * from example_app.orders")

    def test_allows_single_trailing_semicolon(self) -> None:
        self.assertEqual(clean_sql("select 1;"), "select 1")

    def test_allows_show_sql(self) -> None:
        sql = "show create view bi.example_view"

        self.assertEqual(clean_sql(sql), sql)

    def test_select_only_operations_reject_show(self) -> None:
        with self.assertRaises(HTTPException):
            clean_select_sql("show create table bi.example_table")

    def test_explain_wraps_clean_sql(self) -> None:
        self.assertEqual(explain_sql(clean_sql("select 1;")), "EXPLAIN select 1")

    def test_rejects_multiple_statements(self) -> None:
        self.assert_rejected("select 1; select 2")

    def test_rejects_mutation_and_ddl_keywords(self) -> None:
        for sql in [
            "insert into t values (1)",
            "select * from t update",
            "delete from t",
            "drop table t",
            "alter table t add column c int",
            "set @x = 1",
            "call proc()",
            "lock tables t read",
        ]:
            with self.subTest(sql=sql):
                self.assert_rejected(sql)

    def test_rejects_locking_reads(self) -> None:
        for sql in [
            "select * from t for update",
            "select * from t lock in share mode",
            "select * from t for share",
            "select * from t for update nowait",
            "select * from t for update skip locked",
        ]:
            with self.subTest(sql=sql):
                self.assert_rejected(sql)

    def test_rejects_file_and_wait_functions(self) -> None:
        for sql in [
            "select * from t into outfile '/tmp/a'",
            "select load_file('/etc/passwd')",
            "select sleep(1)",
            "select benchmark(1000, md5('x'))",
            "select get_lock('x', 10)",
        ]:
            with self.subTest(sql=sql):
                self.assert_rejected(sql)

    def test_rejects_user_variables(self) -> None:
        for sql in [
            "select password into @stolen from mysql.user where user = 'root'",
            "select password from mysql.user into @stolen",
            "select password into stolen from mysql.user where user = 'root'",
            "select @stolen := password from mysql.user where user = 'root'",
            "select @stolen",
            "with q as (select @stolen := 1) select * from q",
        ]:
            with self.subTest(sql=sql):
                self.assert_rejected(sql)

    def test_rejects_block_comments(self) -> None:
        for sql in [
            "select /* comment */ 1",
            "select /*!50000 sleep(1) */ 1",
            "select /*+ MAX_EXECUTION_TIME(1) */ 1",
            "-- comment\nselect 1",
            "select 1 -- comment",
            "# comment\nselect 1",
            "select 1 # comment",
        ]:
            with self.subTest(sql=sql):
                self.assert_rejected(sql)


if __name__ == "__main__":
    unittest.main()
