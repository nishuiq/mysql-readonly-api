import ssl
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pymysql

from app.config import MysqlConfig, QueryConfig, settings_from_dict
from app.database import Databases, initialize_mysql_session, mysql_connect_args
from app.errors import DatabaseConnectionError


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.mysql = MysqlConfig(host="localhost", username="reader", password="secret", use_ssl=False)

    def test_driver_options_and_actual_tls_enablement(self):
        args = mysql_connect_args(self.mysql)
        self.assertEqual(args["local_infile"], False)
        self.assertEqual(args["read_timeout"], 30)
        self.assertTrue(args["ssl_disabled"])
        secure_args = mysql_connect_args(replace(self.mysql, use_ssl=True))
        self.assertIsInstance(secure_args["ssl"], ssl.SSLContext)
        self.assertEqual(secure_args["ssl"].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(secure_args["ssl"].check_hostname)
        connection = pymysql.connect(defer_connect=True, **secure_args)
        self.assertTrue(connection.ssl)

    def test_initializes_read_only_and_reads_mode(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("NO_BACKSLASH_ESCAPES",)
        self.assertEqual(initialize_mysql_session(connection, self.mysql, QueryConfig()), "NO_BACKSLASH_ESCAPES")
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
        connection = MagicMock(_secure=False)
        with self.assertRaises(DatabaseConnectionError):
            initialize_mysql_session(connection, replace(self.mysql, use_ssl=True), QueryConfig())
        connection.cursor.assert_not_called()

    def test_each_application_owns_and_disposes_its_pools(self):
        settings = settings_from_dict(
            {
                "profiles": {
                    "dev": {
                        "enabled": True,
                        "description": "test",
                        "mysql": {"host": "localhost", "username": "reader", "password": "secret", "use_ssl": False},
                    },
                }
            }
        )
        with patch("app.database.create_mysql_engine", side_effect=[MagicMock(), MagicMock()]):
            first, second = Databases(settings), Databases(settings)
        self.assertIsNot(first.engines["dev"], second.engines["dev"])
        first.dispose()
        first.engines["dev"].dispose.assert_called_once()
        second.engines["dev"].dispose.assert_not_called()
