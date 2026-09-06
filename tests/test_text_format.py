"""覆盖文本原值与 JSON 字段边界的表示契约"""

import json
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.executor import QueryResult
from app.text_format import format_text_rows, format_value, result_response


class TextFormatTest(unittest.TestCase):
    """覆盖文本原值与 JSON 字段边界的表示契约"""

    def test_strings_are_not_modified(self):
        """字符串中的控制字符、反斜杠和零日期前缀保持原样"""
        for value in ["line1\nline2", r"line1\nline2", "a\tb", "a\rb", "NULL", "0000-00-00 text", ""]:
            with self.subTest(value=value):
                self.assertEqual(format_value(value), value)

    def test_truncated_marker_has_no_blank_line_or_paging_details(self):
        """截断标记紧邻表头且不附加分页参数"""
        self.assertEqual(format_text_rows(["id"], [(1,)], True), "[truncated]\nid\n1")
        self.assertEqual(format_text_rows(["id"], [(1,)]), "id\n1")

    def test_empty_and_null_results_succeed(self):
        """空结果与 SQL NULL 都返回成功响应"""
        self.assertEqual(result_response(QueryResult(["v"], [])).body, b"v")
        self.assertEqual(result_response(QueryResult(["v"], [(None,)])).body, b"v\nNULL")

    def test_json_preserves_distinctions_and_duplicate_names(self):
        """JSON 保留 NULL、空字符串、控制字符及重复列名之间的区别"""
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
        """数值精度、日期、长时长和二进制按既定约定展示"""
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
