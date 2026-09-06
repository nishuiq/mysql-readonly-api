"""覆盖数据库错误分类与纯文本 HTTP 错误契约"""

import ssl
import unittest

import pymysql
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, ProgrammingError, TimeoutError

from app.errors import database_error, register_exception_handlers


def sql_error(number, message):
    """构造携带敏感上下文的数据库异常样本

    Args:
        number: 模拟的 MySQL 错误号
        message: 模拟的驱动消息

    Returns:
        包含 SQL 与绑定参数的包装异常，供脱敏断言使用
    """
    return ProgrammingError(
        "SELECT secret FROM private", {"password": "secret"}, pymysql.err.ProgrammingError(number, message)
    )


class ErrorsTest(unittest.TestCase):
    """覆盖数据库错误分类与纯文本 HTTP 错误契约"""

    def test_tls_error_identifies_certificate_problem_without_exposing_host(self):
        """证书错误说明 TLS 失败原因且不暴露连接地址"""
        original = pymysql.err.OperationalError(2003, "Could not connect to private-host")
        original.original_exception = ssl.SSLCertVerificationError("private certificate detail")
        status, message = database_error(OperationalError("", {}, original))
        self.assertEqual(status, 503)
        self.assertIn("TLS certificate verification failed", message)
        self.assertNotIn("private", message)

    def test_mysql_error_is_actionable_without_sqlalchemy_wrapper(self):
        """查询错误保留错误号和原因且不附加 SQL 与参数"""
        status, message = database_error(sql_error(1054, "Unknown column 'missing' in 'field list'"))
        self.assertEqual(status, 400)
        self.assertIn("MySQL 1054", message)
        self.assertIn("missing", message)
        self.assertNotIn("secret", message)
        self.assertNotIn("SELECT", message)

    def test_connection_details_are_hidden(self):
        """连接认证错误不会回显账号或主机"""
        status, message = database_error(
            OperationalError(
                "", {}, pymysql.err.OperationalError(1045, "Access denied for user 'private-user'@'private-host'")
            )
        )
        self.assertEqual(status, 503)
        self.assertNotIn("private", message)

    def test_error_categories(self):
        """数据库错误映射到相应 HTTP 状态与可处理提示"""
        for number, expected in [
            (1142, 403),
            (1792, 403),
            (1146, 404),
            (3024, 504),
            (2013, 503),
            (1064, 400),
            (1060, 400),
        ]:
            with self.subTest(number=number):
                self.assertEqual(database_error(sql_error(number, "driver message"))[0], expected)
        self.assertIn("alias", database_error(sql_error(1060, "duplicate"))[1])
        self.assertEqual(database_error(TimeoutError())[0], 503)

    def test_framework_errors_are_text_and_keep_allow_header(self):
        """框架错误使用纯文本且保留方法约束响应头"""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/error")
        def error():
            """触发具有固定消息的 HTTP 错误

            Raises:
                HTTPException: 始终抛出状态为 403 的错误
            """
            raise HTTPException(403, "No access.")

        with TestClient(app) as client:
            for path, expected in [("/absent", 404), ("/error", 403)]:
                response = client.get(path)
                self.assertEqual(response.status_code, expected)
                self.assertTrue(response.headers["content-type"].startswith("text/plain"))
            response = client.post("/error")
            self.assertEqual(response.status_code, 405)
            self.assertIn("GET", response.headers["allow"])
