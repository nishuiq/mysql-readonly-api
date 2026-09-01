import unittest

from app.text_format import format_text_rows, format_value, raw_value_response


class TextFormatTest(unittest.TestCase):
    def test_zero_datetime_behavior_is_request_specific(self) -> None:
        value = "0000-00-00 00:00:00"

        self.assertEqual(format_value(value, "convert_to_null"), "NULL")
        self.assertEqual(format_value(value, "preserve"), value)

    def test_formats_tab_separated_rows(self) -> None:
        result = format_text_rows(["name", "note"], [("dev", "line 1\nline 2")])

        self.assertEqual(result, "name\tnote\ndev\tline 1\\nline 2")

    def test_raw_value_preserves_text_exactly(self) -> None:
        value = "BEGIN\r\n\tSELECT 'literal \\n';\n中文\nEND"

        response = raw_value_response("definition", value)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, ("definition\n" + value).encode("utf-8"))

    def test_raw_null_uses_no_content(self) -> None:
        response = raw_value_response("definition", None)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.body, b"")

    def test_raw_bytes_are_returned_as_plain_text(self) -> None:
        response = raw_value_response("definition", b"left\tright\n")

        self.assertEqual(response.headers["content-type"], "text/plain; charset=utf-8")
        self.assertEqual(response.body, b"definition\nleft\tright\n")


if __name__ == "__main__":
    unittest.main()
