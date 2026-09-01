import unittest

from app.config import MysqlConfig, MysqlPoolConfig, QueryConfig
from app.database import initialize_mysql_session, mysql_connect_args


class RecordingCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.calls.append((sql, params))


class RecordingConnection:
    def __init__(self) -> None:
        self.recording_cursor = RecordingCursor()

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor


def mysql_config(server_timezone: str = "+08:00") -> MysqlConfig:
    return MysqlConfig(
        host="127.0.0.1",
        port=3306,
        username="readonly",
        password="password",
        use_unicode=True,
        character_encoding="utf8",
        zero_datetime_behavior="convert_to_null",
        use_ssl=False,
        server_timezone=server_timezone,
        pool=MysqlPoolConfig(
            size=5,
            max_overflow=10,
            timeout=30,
            recycle=3600,
            pre_ping=True,
        ),
    )


class DatabaseTest(unittest.TestCase):
    def test_connect_args_only_contain_driver_options(self) -> None:
        self.assertEqual(
            mysql_connect_args(mysql_config()),
            {
                "charset": "utf8",
                "use_unicode": True,
            },
        )

    def test_initializes_each_new_session_as_read_only(self) -> None:
        connection = RecordingConnection()

        initialize_mysql_session(
            connection,
            mysql_config(),
            QueryConfig(default_limit=500, max_limit=5000, timeout_ms=15000),
        )

        self.assertEqual(
            connection.recording_cursor.calls,
            [
                ("SET SESSION TRANSACTION READ ONLY", None),
                ("SET SESSION time_zone = %s", ("+08:00",)),
                ("SET SESSION max_execution_time = %s", (15000,)),
            ],
        )


if __name__ == "__main__":
    unittest.main()
