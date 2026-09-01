import unittest
from unittest.mock import Mock, patch

from app.executor import RawQueryValue
from app.query import query_raw, query_text


class QueryTest(unittest.TestCase):
    def test_show_executes_without_paging_wrapper(self) -> None:
        session = Mock()
        context = Mock()
        context.__enter__ = Mock(return_value=session)
        context.__exit__ = Mock(return_value=False)

        with patch("app.query.db_session", return_value=context), patch(
            "app.query.run_sql", return_value="result"
        ) as run_sql:
            result = query_text("example", "show create table app.orders", limit=10, offset=0)

        self.assertEqual(result, "result")
        run_sql.assert_called_once_with(session, "show create table app.orders")

    def test_raw_select_uses_two_row_shape_guard(self) -> None:
        session = Mock()
        context = Mock()
        context.__enter__ = Mock(return_value=session)
        context.__exit__ = Mock(return_value=False)
        raw_value = RawQueryValue(column="definition", value="body")

        with patch("app.query.db_session", return_value=context), patch(
            "app.query.run_raw_sql", return_value=raw_value
        ) as run_raw_sql:
            result = query_raw("example", "select definition from app.routines")

        self.assertEqual(result, raw_value)
        called_sql = run_raw_sql.call_args.args[1]
        self.assertIn("LIMIT :_codex_limit OFFSET :_codex_offset", called_sql)
        self.assertEqual(run_raw_sql.call_args.kwargs["params"]["_codex_limit"], 2)


if __name__ == "__main__":
    unittest.main()
