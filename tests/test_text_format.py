import unittest

from app.text_format import format_text_rows, format_value


class TextFormatTest(unittest.TestCase):
    def test_zero_datetime_behavior_is_request_specific(self) -> None:
        value = "0000-00-00 00:00:00"

        self.assertEqual(format_value(value, "convert_to_null"), "NULL")
        self.assertEqual(format_value(value, "preserve"), value)

    def test_formats_tab_separated_rows(self) -> None:
        result = format_text_rows(["name", "note"], [("dev", "line 1\nline 2")])

        self.assertEqual(result, "name\tnote\ndev\tline 1\\nline 2")


if __name__ == "__main__":
    unittest.main()
