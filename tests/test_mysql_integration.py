"""在显式指定的测试实例中检查真实 MySQL 行为"""

import os
import unittest
import uuid

import pymysql
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings_from_dict
from app.ddl import sql_string
from app.errors import mysql_error_number
from app.factory import create_app
from app.query import query_result
from tests.helpers import example_config


@unittest.skipUnless(os.environ.get("MYSQL_TEST_PORT"), "Set MYSQL_TEST_PORT for a dedicated MySQL test instance.")
class MySQLIntegrationTest(unittest.TestCase):
    """在显式指定的测试实例中检查真实 MySQL 行为"""

    @classmethod
    def setUpClass(cls):
        """创建随机命名的隔离 schema 和只读 API 客户端

        Raises:
            pymysql.Error: 测试实例不可连接或测试账号无法建立所需对象
        """
        config = example_config()
        cls.mysql = config["profiles"]["example-dev"]["mysql"]
        cls.mysql.update(
            {
                "host": os.environ.get("MYSQL_TEST_HOST", "127.0.0.1"),
                "port": int(os.environ["MYSQL_TEST_PORT"]),
                "username": os.environ.get("MYSQL_TEST_USER", "root"),
                "password": os.environ.get("MYSQL_TEST_PASSWORD", ""),
                "use_ssl": False,
            }
        )
        cls.admin = pymysql.connect(
            host=cls.mysql["host"],
            port=cls.mysql["port"],
            user=cls.mysql["username"],
            password=cls.mysql["password"],
            charset="utf8mb4",
            autocommit=True,
            ssl_disabled=True,
        )
        cls.addClassCleanup(cls.admin.close)
        cls.schema = "readonly_api_test_" + uuid.uuid4().hex
        with cls.admin.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            cls.version = tuple(int(part) for part in cursor.fetchone()[0].split("-")[0].split("."))
            cursor.execute(f"CREATE DATABASE {cls.schema} CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
        cls.addClassCleanup(cls.drop_schema)
        cls.source = "line1\nline2\t\r\\n :name 100% 中文 😀𠀀"
        with cls.admin.cursor() as cursor:
            cursor.execute("SET SESSION sql_mode = 'NO_ENGINE_SUBSTITUTION'")
            cursor.execute(f"""
                CREATE TABLE {cls.schema}.sample (
                    `a-b` int NOT NULL PRIMARY KEY,
                    label varchar(100) DEFAULT 'NULL',
                    choices enum('x,1','int(11)') DEFAULT 'x,1',
                    body text,
                    amount decimal(30,6),
                    duration time(6),
                    zero_date date,
                    `generated` int GENERATED ALWAYS AS (`a-b` + 1) STORED,
                    INDEX body_prefix (body(10))
                ) ENGINE=InnoDB COMMENT='table comment'
            """)
            cursor.executemany(
                f"INSERT INTO {cls.schema}.sample (`a-b`, body, amount, duration) VALUES (%s,%s,%s,%s)",
                [
                    (1, cls.source, "12345678901234567890.123450", "-49:00:00.000001"),
                    (2, None, "0.000000", "00:00:00"),
                    (3, "", None, None),
                ],
            )
            cursor.execute(f"UPDATE {cls.schema}.sample SET zero_date='0000-00-00' WHERE `a-b`=1")
            cursor.execute(f"CREATE VIEW {cls.schema}.`view:100%` AS SELECT `a-b` FROM {cls.schema}.sample")
            cursor.execute(f"""CREATE PROCEDURE {cls.schema}.p()
                BEGIN
                    SELECT 'literal\\\\n' AS body;
                    SELECT 'second line' AS body;
                END""")
            cursor.execute(f"""CREATE EVENT {cls.schema}.e ON SCHEDULE EVERY 1 DAY DISABLE
                DO BEGIN
                    SELECT 'event body';
                END""")
            if cls.version >= (8, 0, 16):
                cursor.execute(f"ALTER TABLE {cls.schema}.sample ADD CONSTRAINT positive CHECK (`a-b` > 0)")
                cursor.execute(f"CREATE INDEX label_desc ON {cls.schema}.sample (label DESC) INVISIBLE")
                cursor.execute(f"CREATE INDEX label_expression ON {cls.schema}.sample ((lower(label)))")
        config["profiles"] = {
            "test": {"description": "Isolated integration test", "enabled": True, "mysql": cls.mysql},
        }
        cls.app = create_app(settings_from_dict(config))
        cls.client = TestClient(cls.app)
        cls.client.__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)

    @classmethod
    def drop_schema(cls):
        """清理当前测试类创建的隔离 schema

        Raises:
            pymysql.Error: 测试实例拒绝清理或连接失效
        """
        with cls.admin.cursor() as cursor:
            cursor.execute(f"DROP DATABASE {cls.schema}")

    def query(self, sql, suffix="?format=json", operation="query"):
        """向隔离环境发送原始 SQL

        Args:
            sql: 提交给测试 API 的 SQL 字符串
            suffix: 附加到端点的查询参数，省略时选择 JSON
            operation: query、count 或 explain 端点名称

        Returns:
            测试客户端收到的 HTTP 响应
        """
        return self.client.post(
            f"/profiles/test/{operation}{suffix}",
            content=sql.encode("utf-8"),
            headers={"content-type": "text/plain; charset=utf-8"},
        )

    def test_original_sql_and_text_values_round_trip(self):
        """SQL 特殊字符和数据库文本经两种格式往返后保持原意"""
        response = self.query("SELECT ':name' AS a, '%(x)s 100%' AS b, REPLACE('create;', ';', '#') AS c")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["rows"], [[":name", "%(x)s 100%", "create#"]])
        sql = f"SELECT body FROM {self.schema}.sample WHERE `a-b`=1"
        self.assertEqual(self.query(sql).json()["rows"], [[self.source]])
        self.assertEqual(self.query(sql, suffix="").text, "body\n" + self.source)

    def test_paging_and_exact_truncation_boundary(self):
        """分页在实际额外行存在时才标记截断"""
        sql = f"SELECT `a-b` AS id FROM {self.schema}.sample ORDER BY `a-b`"
        small = self.query(sql, "?format=json&limit=2")
        self.assertEqual(small.json(), {"columns": ["id"], "rows": [[1], [2]], "truncated": True})
        self.assertEqual(self.query(sql, "?limit=2").text, "[truncated]\nid\n1\n2")
        self.assertFalse(self.query(sql, "?format=json&limit=3").json()["truncated"])
        self.assertEqual(self.query(sql, "?format=json&limit=2&offset=2").json()["rows"], [[3]])
        inner = self.query(sql + " LIMIT 1", "?format=json&limit=2")
        self.assertEqual(inner.json()["rows"], [[1]])
        self.assertFalse(inner.json()["truncated"])
        self.assertEqual(self.query(sql, "?format=json&offset=5").json()["rows"], [])

    def test_null_empty_string_and_scalar_types(self):
        """真实驱动区分空值并保留零日期、精确小数和负时长"""
        result = self.query(f"SELECT body FROM {self.schema}.sample ORDER BY `a-b`").json()
        self.assertEqual(result["rows"], [[self.source], [None], [""]])
        result = self.query(
            f"SELECT amount, duration, zero_date, "
            f"'0000-00-00 normal text' AS literal, X'00FF' AS binary_value FROM {self.schema}.sample WHERE `a-b`=1"
        ).json()
        self.assertEqual(
            result["rows"][0],
            [
                "12345678901234567890.123450",
                "-49:00:00.000001",
                "0000-00-00",
                "0000-00-00 normal text",
                {"hex": "00ff"},
            ],
        )

    def test_show_create_procedure_event_and_view(self):
        """过程、事件和视图源码与 MySQL 原生返回一致"""
        for kind, name, column in [
            ("PROCEDURE", "p", "Create Procedure"),
            ("EVENT", "e", "Create Event"),
            ("VIEW", "`view:100%`", "Create View"),
        ]:
            with self.subTest(kind=kind):
                sql = f"SHOW CREATE {kind} {self.schema}.{name}"
                with self.admin.cursor() as cursor:
                    cursor.execute(sql)
                    original = cursor.fetchone()
                    columns = [description[0] for description in cursor.description]
                response = self.query(sql)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["rows"][0][columns.index(column)], original[columns.index(column)])
        response = self.query("SHOW VARIABLES", "?format=json&limit=2")
        self.assertEqual(len(response.json()["rows"]), 2)
        self.assertTrue(response.json()["truncated"])
        self.assertEqual(self.query("SHOW VARIABLES", "?offset=1").status_code, 422)

    def test_ddl_metadata_uses_supported_version_fields(self):
        """DDL 元数据按实际服务端版本正确查询和展示"""
        response = self.client.get("/profiles/test/ddl", params={"schema": self.schema, "table": "sample,sample"})
        self.assertEqual(response.status_code, 200, response.text)
        ddl = response.text
        self.assertEqual(ddl.count("create table sample"), 1)
        self.assertIn("`a-b`", ddl)
        self.assertIn("primary key", ddl)
        self.assertIn("default 'NULL'", ddl)
        self.assertIn("enum('x,1','int(11)')", ddl)
        self.assertIn("stored", ddl)
        self.assertIn("body(10)", ddl)
        if self.version >= (8, 0, 16):
            self.assertIn("label desc", ddl)
            self.assertIn("invisible", ddl)
            self.assertIn("lower(", ddl)
            self.assertIn("check (", ddl)
        response = self.client.get("/profiles/test/ddl", params={"schema": self.schema, "table": "view:100%"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("VIEW", response.text)
        response = self.client.get(
            "/profiles/test/tables", params={"schema": self.schema, "format": "json", "limit": 1}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Type", response.json()["columns"])
        self.assertTrue(response.json()["truncated"])

    def test_read_only_session_is_enforced_by_mysql_and_pool_reuse(self):
        """MySQL 拒绝只读会话写入且连接复用不解除限制"""
        for _ in range(2):
            with self.app.state.databases.session("test") as session:
                with self.assertRaises(SQLAlchemyError) as error:
                    session.connection().exec_driver_sql(f"INSERT INTO {self.schema}.sample (`a-b`) VALUES (9)")
                self.assertEqual(mysql_error_number(error.exception), 1792)
        response = self.query("SELECT @@session.max_execution_time AS timeout_ms")
        self.assertEqual(response.json()["rows"], [[15000]])

    def test_sql_modes_preserve_literal_values(self):
        """不同 SQL mode 下的字符串引用仍返回相同字段值"""
        value = "quote' slash\\ newline\n 中文"
        with self.app.state.databases.session("test") as session:
            connection = session.connection()
            original = session.info["sql_mode"]
            try:
                for mode in ["", "NO_BACKSLASH_ESCAPES", "ANSI_QUOTES,NO_BACKSLASH_ESCAPES"]:
                    connection.exec_driver_sql("SET SESSION sql_mode = %s", (mode,))
                    session.info["sql_mode"] = connection.exec_driver_sql("SELECT @@SESSION.sql_mode").scalar_one()
                    literal = sql_string(value, no_backslash="NO_BACKSLASH_ESCAPES" in mode)
                    result = query_result(session, f"SELECT {literal} AS body", 2, 0)
                    self.assertEqual(result.rows, [(value,)])
            finally:
                connection.exec_driver_sql("SET SESSION sql_mode = %s", (original,))
                session.info["sql_mode"] = original

    @unittest.skipUnless(os.environ.get("MYSQL_TEST_SSL_CA"), "Set MYSQL_TEST_SSL_CA to verify live TLS.")
    def test_tls_connection_uses_trusted_certificate(self):
        """可信 CA 配置能够建立实际加密连接"""
        mysql = {**self.mysql, "use_ssl": True, "ssl_ca": os.environ["MYSQL_TEST_SSL_CA"]}
        config = example_config()
        config["profiles"] = {
            "test": {"enabled": True, "description": "TLS integration test", "mysql": mysql},
        }
        settings = settings_from_dict(config)
        with TestClient(create_app(settings)) as client:
            response = client.post(
                "/profiles/test/query?format=json",
                content="SHOW SESSION STATUS LIKE 'Ssl_cipher'",
                headers={"content-type": "text/plain"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["rows"][0][1])

    def test_native_errors_count_explain_and_cte_version(self):
        """原生错误、计数和执行计划符合各 MySQL 版本行为"""
        for sql, expected, phrase in [
            ("SELECT missing_column", 400, "1054"),
            (f"SELECT * FROM {self.schema}.missing_table", 404, "1146"),
            ("SELECT 1 AS x, 2 AS x", 400, "alias"),
        ]:
            with self.subTest(sql=sql):
                response = self.query(sql)
                self.assertEqual(response.status_code, expected, response.text)
                self.assertIn(phrase, response.text)
                self.assertTrue(response.headers["content-type"].startswith("text/plain"))
        sql = f"SELECT * FROM {self.schema}.sample LIMIT 2 -- final comment"
        self.assertEqual(self.query(sql, operation="count").json()["rows"], [[2]])
        self.assertEqual(self.query(sql, operation="explain").status_code, 200)
        response = self.query("WITH q AS (SELECT 1 AS id) SELECT id FROM q")
        self.assertEqual(response.status_code, 200 if self.version >= (8, 0) else 400)
