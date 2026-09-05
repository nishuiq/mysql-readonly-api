import json
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.executor import QueryResult
from app.text_format import format_text_rows, format_value, result_response


class TextFormatTest(unittest.TestCase):
    def test_strings_are_not_modified(self):
        for value in ["line1\nline2", r"line1\nline2", "a\tb", "a\rb", "NULL", "0000-00-00 text", ""]:
            with self.subTest(value=value):
                self.assertEqual(format_value(value), value)

    def test_truncated_marker_has_no_blank_line_or_paging_details(self):
        self.assertEqual(format_text_rows(["id"], [(1,)], True), "[truncated]\nid\n1")
        self.assertEqual(format_text_rows(["id"], [(1,)]), "id\n1")

    def test_empty_and_null_results_succeed(self):
        self.assertEqual(result_response(QueryResult(["v"], [])).body, b"v")
        self.assertEqual(result_response(QueryResult(["v"], [(None,)])).body, b"v\nNULL")

    def test_json_preserves_distinctions_and_duplicate_names(self):
        values = (None, "NULL", r"\N", "\n\t\r\\", "", b"\x00\xff")
        response = result_response(QueryResult(["v"] * 6, [values], True), "json")
        self.assertEqual(
            json.loads(response.body),
            {
                "columns": ["v"] * 6,
                "rows": [[None, "NULL", r"\N", "\n\t\r\\", "", {"hex": "00ff"}]],
                "truncated": True,
            },
        )
        self.assertNotIn(b": ", response.body)

    def test_mysql_scalar_conventions(self):
        values = (
            Decimal("12345678901234567890.123450"),
            date(2025, 1, 2),
            datetime(2025, 1, 2, 3, 4, 5),
            timedelta(hours=-49, microseconds=-1),
        )
        actual = json.loads(result_response(QueryResult(["a", "b", "c", "d"], [values]), "json").body)
        self.assertEqual(
            actual["rows"][0],
            [
                "12345678901234567890.123450",
                "2025-01-02",
                "2025-01-02 03:04:05",
                "-49:00:00.000001",
            ],
        )
        self.assertEqual(format_value(b"\x00\xff"), "0x00ff")
