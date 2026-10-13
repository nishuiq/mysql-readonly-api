"""覆盖查询分派、额外行探测与原始 SQL 传递"""

import unittest
from unittest.mock import MagicMock, Mock, patch

from fastapi import HTTPException

from app.executor import QueryResult, read_result, run_query
from app.query import count_result, explain_result, query_result
from app.sql_guard import tokens


class QueryTest(unittest.TestCase):
    """覆盖查询分派、额外行探测与原始 SQL 传递"""

    def setUp(self):
        """准备携带普通 SQL mode 的替代会话"""
        self.session = Mock(info={"sql_mode": ""})

    def test_show_is_unwrapped_but_limited(self):
        """SHOW 直接执行且限制返回行数并拒绝非零偏移"""
        with patch("app.query.run_query", return_value="result") as execute:
            self.assertEqual(query_result(self.session, "show create event app.e", 2, 0), "result")
        execute.assert_called_once_with(self.session, "show create event app.e", limit=2)
        with self.assertRaisesRegex(HTTPException, "SHOW does not support"):
            query_result(self.session, "show tables", 2, 1)

    def test_select_fetches_limit_plus_one(self):
        """SELECT 外层多取一行并保留内部 LIMIT"""
        with patch("app.query.run_query") as execute:
            query_result(self.session, "select 1 limit 1", 2, 4)
        self.assertIn("select 1 limit 1\n)", execute.call_args.args[1])
        self.assertIn("LIMIT 3 OFFSET 4", execute.call_args.args[1])

    def test_query_count_and_explain_scan_sql_once(self):
        """查询、计数和计划复用单次词法扫描且原样传递有效 SQL"""
        for sql in ["/* header */ SELECT 'show; with' AS v; -- keep", "WITH q AS (SELECT 1 AS v) SELECT v FROM q;"]:
            cleaned = sql.replace("; -- keep", " -- keep").removesuffix(";")
            for operation, args, expected_sql in [
                (query_result, (2, 0), f"SELECT *\nFROM (\n{cleaned}\n) AS _codex_query\nLIMIT 3 OFFSET 0"),
                (count_result, (), f"SELECT COUNT(*) AS count FROM (\n{cleaned}\n) AS _count_query"),
                (explain_result, (2,), f"EXPLAIN {cleaned}"),
            ]:
                with self.subTest(operation=operation.__name__, sql=sql):
                    with patch("app.sql_guard.tokens", wraps=tokens) as scan, patch("app.query.run_query") as execute:
                        operation(self.session, sql, *args)
                    scan.assert_called_once_with(sql, "")
                    execute.assert_called_once()
                    self.assertEqual(execute.call_args.args[1], expected_sql)

    def test_show_dispatch_reuses_scan_and_preserves_comments(self):
        """带注释的 SHOW 只扫描一次且保持直接执行和偏移限制"""
        sql = "/* SELECT */ ShOw CREATE TABLE `with`; -- keep"
        for offset in [0, 1]:
            with self.subTest(offset=offset):
                with patch("app.sql_guard.tokens", wraps=tokens) as scan, patch("app.query.run_query") as execute:
                    if offset:
                        with self.assertRaises(HTTPException) as error:
                            query_result(self.session, sql, 2, offset)
                        self.assertEqual(error.exception.status_code, 422)
                        execute.assert_not_called()
                    else:
                        query_result(self.session, sql, 2, offset)
                        execute.assert_called_once_with(
                            self.session, "/* SELECT */ ShOw CREATE TABLE `with` -- keep", limit=2
                        )
                scan.assert_called_once_with(sql, "")

    def test_all_query_operations_reject_unsafe_sql_before_execution(self):
        """全部查询入口在执行前拒绝危险 SQL 并遵循会话引用规则"""
        for operation, args in [(query_result, (2, 0)), (count_result, ()), (explain_result, (2,))]:
            for sql, mode in [
                ("SELECT 1; SELECT 2", ""),
                ("WITH q AS (SELECT 1) DELETE FROM t", ""),
                ("SELECT * FROM t FOR UPDATE", ""),
                ("SELECT `sleep`(1)", ""),
                ("SHOW TABLES WHERE @x:=1", ""),
                ("SELECT /*+ MAX_EXECUTION_TIME(0) */ 1", ""),
                (r"SELECT 'a\'; SELECT 2 -- '", "NO_BACKSLASH_ESCAPES"),
                ('SELECT "sleep"(1)', "ANSI_QUOTES"),
            ]:
                with self.subTest(operation=operation.__name__, sql=sql, mode=mode):
                    self.session.info["sql_mode"] = mode
                    with patch("app.query.run_query") as execute, self.assertRaises(HTTPException) as error:
                        operation(self.session, sql, *args)
                    self.assertEqual(error.exception.status_code, 400)
                    execute.assert_not_called()

    def test_count_and_explain_reject_show_before_execution(self):
        """计数和计划拒绝通过只读校验的 SHOW 且不访问数据库"""
        for operation, args in [(count_result, ()), (explain_result, (2,))]:
            with self.subTest(operation=operation.__name__):
                with patch("app.query.run_query") as execute, self.assertRaises(HTTPException) as error:
                    operation(self.session, "/* SELECT */ SHOW TABLES", *args)
                self.assertEqual(error.exception.status_code, 400)
                execute.assert_not_called()

    def test_truncation_is_based_on_extra_row(self):
        """只有读取到额外一行时才标记截断"""
        for rows, expected in [([], False), ([(1,)], False), ([(1,), (2,)], False), ([(1,), (2,), (3,)], True)]:
            with self.subTest(rows=rows):
                result = Mock(returns_rows=True)
                result.keys.return_value = ["id"]
                result.fetchmany.return_value = rows
                self.assertEqual(read_result(result, 2), QueryResult(["id"], rows[:2], expected))
                result.fetchmany.assert_called_once_with(3)
                result.fetchall.assert_not_called()

    def test_user_sql_is_never_bound_as_a_template(self):
        """用户 SQL 中的冒号和百分号不会作为参数模板解释"""
        session = MagicMock()
        cursor = session.connection.return_value.exec_driver_sql.return_value.__enter__.return_value
        cursor.keys.return_value = ["v"]
        cursor.fetchall.return_value = [(":name 100% %(x)s",)]
        sql = "select ':name 100% %(x)s' as v"
        self.assertEqual(run_query(session, sql).rows, [(":name 100% %(x)s",)])
        session.connection.return_value.exec_driver_sql.assert_called_once_with(
            sql,
            execution_options={"no_parameters": True},
        )
