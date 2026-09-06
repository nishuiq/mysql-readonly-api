"""覆盖查询分派、额外行探测与原始 SQL 传递"""

import unittest
from unittest.mock import MagicMock, Mock, patch

from fastapi import HTTPException

from app.executor import QueryResult, read_result, run_query
from app.query import query_result


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
