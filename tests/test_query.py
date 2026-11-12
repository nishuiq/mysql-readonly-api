"""覆盖 SQL 行数限制、结果偏移和流式执行"""

import unittest
from unittest.mock import MagicMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.executor import QueryResult, read_result, run_query
from app.query import query_result


class QueryTest(unittest.TestCase):
    """覆盖查询执行边界和结果分页"""

    def setUp(self):
        """准备携带普通 SQL mode 的替代会话"""
        self.session = Mock(info={"sql_mode": ""})

    def test_query_keeps_explicit_limit_show_and_explain(self):
        """已有 LIMIT、SHOW 和执行计划均保持原文"""
        for sql in ["  SELECT 1 AS x, 2 AS x LIMIT 5  ", "SHOW VARIABLES", "EXPLAIN SELECT 1"]:
            with self.subTest(sql=sql), patch("app.query.run_query", return_value="result") as execute:
                self.assertEqual(query_result(self.session, sql, 2, 4), "result")
                execute.assert_called_once_with(self.session, sql, limit=2, offset=4)

    def test_query_appends_limit_only_when_missing(self):
        """无最外层 LIMIT 的查询在原文后添加接口分页"""
        for sql in ["SELECT 1 AS x", "SELECT * FROM (SELECT 1 AS x LIMIT 10000) q"]:
            with self.subTest(sql=sql), patch("app.query.run_query", return_value="result") as execute:
                self.assertEqual(query_result(self.session, sql, 2, 4), "result")
                execute.assert_called_once_with(self.session, sql + "\nLIMIT 3 OFFSET 4", limit=2, offset=0)

    def test_invalid_sql_never_reaches_executor(self):
        """危险 SQL 和超限查询在数据库执行前被拒绝"""
        for sql in ["SELECT 1; SELECT 2", "EXPLAIN ANALYZE SELECT 1", "SELECT 1 LIMIT 5001"]:
            with self.subTest(sql=sql), patch("app.query.run_query") as execute, self.assertRaises(HTTPException):
                query_result(self.session, sql, 2, 0)
            execute.assert_not_called()

    def test_offset_and_truncation_use_original_result(self):
        """跳过偏移后仅在存在额外一行时标记截断"""
        result = Mock(returns_rows=True)
        result.keys.return_value = ["id"]
        result.fetchmany.side_effect = [[(1,), (2,)], [(3,), (4,), (5,)]]
        self.assertEqual(read_result(result, 2, 2), QueryResult(["id"], [(3,), (4,)], True))
        self.assertEqual([call.args[0] for call in result.fetchmany.call_args_list], [2, 3])

        result.fetchmany.reset_mock(side_effect=True)
        result.fetchmany.return_value = []
        self.assertEqual(read_result(result, 2, 4), QueryResult(["id"], []))
        result.fetchmany.assert_called_once_with(4)

    def test_user_sql_is_executed_without_session_changes(self):
        """用户 SQL 以流式游标执行且不设置会话变量"""
        session = MagicMock()
        connection = session.connection.return_value
        result = MagicMock()
        result.__enter__.return_value.returns_rows = True
        result.__enter__.return_value.keys.return_value = ["v"]
        result.__enter__.return_value.fetchmany.return_value = [(1,)]
        connection.exec_driver_sql.return_value = result
        sql = "SELECT ':name 100% %(x)s' AS v"
        self.assertEqual(run_query(session, sql, 2, 0), QueryResult(["v"], [(1,)]))
        connection.exec_driver_sql.assert_called_once_with(
            sql, execution_options={"no_parameters": True, "stream_results": True}
        )

    def test_query_failure_is_propagated(self):
        """数据库错误直接传递且不执行额外语句"""
        session = MagicMock()
        connection = session.connection.return_value
        connection.exec_driver_sql.side_effect = SQLAlchemyError("query failed")
        with self.assertRaisesRegex(SQLAlchemyError, "query failed"):
            run_query(session, "SELECT 1", 2, 0)
        connection.exec_driver_sql.assert_called_once()
