"""覆盖驱动参数、只读初始化与连接池所有权"""

import ssl
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pymysql

from app.config import QueryConfig, settings_from_dict
from app.database import Databases, initialize_mysql_session, mysql_connect_args
from app.errors import DatabaseConnectionError
from tests.helpers import example_config, example_mysql


class DatabaseTest(unittest.TestCase):
    """覆盖驱动参数、只读初始化与连接池所有权"""

    def setUp(self):
        """从完整示例配置准备不启用 TLS 的连接参数"""
        self.mysql = replace(example_mysql(), use_ssl=False)

    def test_driver_options_and_actual_tls_enablement(self):
        """驱动参数关闭文件导入且 TLS 上下文实际启用证书校验"""
        args = mysql_connect_args(replace(self.mysql, io_timeout=17))
        self.assertEqual(args["local_infile"], False)
        self.assertEqual(args["read_timeout"], 17)
        self.assertEqual(args["write_timeout"], 17)
        self.assertTrue(args["ssl_disabled"])
        secure_args = mysql_connect_args(replace(self.mysql, use_ssl=True))
        self.assertIsInstance(secure_args["ssl"], ssl.SSLContext)
        self.assertEqual(secure_args["ssl"].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(secure_args["ssl"].check_hostname)
        connection = pymysql.connect(defer_connect=True, **secure_args)
        self.assertTrue(connection.ssl)

    def test_initializes_read_only_and_reads_mode(self):
        """每个物理连接设置只读与超时并读取真实 SQL mode"""
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("NO_BACKSLASH_ESCAPES",)
        self.assertEqual(
            initialize_mysql_session(connection, self.mysql, QueryConfig(limit=500, timeout_ms=15000)),
            "NO_BACKSLASH_ESCAPES",
        )
        self.assertEqual(
            [call.args for call in cursor.execute.call_args_list],
            [
                ("SET SESSION TRANSACTION READ ONLY",),
                ("SET SESSION time_zone = %s", ("+08:00",)),
                ("SET SESSION max_execution_time = %s", (15000,)),
                ("SELECT @@SESSION.sql_mode",),
            ],
        )

    def test_tls_cannot_silently_fall_back_to_plaintext(self):
        """要求 TLS 时拒绝静默降级的明文连接"""
        connection = MagicMock(_secure=False)
        with self.assertRaises(DatabaseConnectionError):
            initialize_mysql_session(
                connection, replace(self.mysql, use_ssl=True), QueryConfig(limit=500, timeout_ms=15000)
            )
        connection.cursor.assert_not_called()

    def test_each_application_owns_and_disposes_its_pools(self):
        """不同应用的连接池独立创建和释放"""
        config = example_config()
        config["profiles"]["example-dev"]["enabled"] = True
        settings = settings_from_dict(config)
        with patch("app.database.create_mysql_engine", side_effect=[MagicMock(), MagicMock()]):
            first, second = Databases(settings), Databases(settings)
        self.assertIsNot(first.engines["example-dev"], second.engines["example-dev"])
        first.dispose()
        first.engines["example-dev"].dispose.assert_called_once()
        second.engines["example-dev"].dispose.assert_not_called()
