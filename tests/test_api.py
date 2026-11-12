"""覆盖 REST 参数、结果格式与应用配置边界"""

import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api import get_session
from app.config import settings_from_dict
from app.executor import QueryResult
from app.factory import create_app
from tests.helpers import example_config


class ApiTest(unittest.TestCase):
    """覆盖 REST 参数、结果格式与应用配置边界"""

    def setUp(self):
        """准备使用显式行数上限和替代会话的 API 客户端"""
        config = example_config()
        config["query"]["limit"] = 2
        config["profiles"] = {}
        self.app = create_app(settings_from_dict(config))
        self.session = Mock(info={"sql_mode": "", "mysql_version": (5, 7, 44)})
        self.app.dependency_overrides[get_session] = lambda: self.session
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def post(self, path="/query", **kwargs):
        """发送固定 SQL 的 API 请求

        Args:
            path: 环境路径之后的端点和查询参数，省略时请求 query
            kwargs: 转交给测试客户端的附加请求参数

        Returns:
            测试客户端收到的 HTTP 响应
        """
        return self.client.post(
            "/profiles/test" + path, content="select 1", headers={"content-type": "text/plain"}, **kwargs
        )

    def test_query_formats_and_configured_limit(self):
        """默认和显式 TSV 保留截断状态且 JSON 保持原有结构"""
        with patch("app.api.query_result", return_value=QueryResult(["id"], [(1,), (2,)], True)) as query:
            response = self.post()
            self.assertEqual(response.text, "[truncated]\nid\n1\n2")
            self.assertEqual(response.headers["content-type"], "text/tab-separated-values; charset=utf-8")
            query.assert_called_with(self.session, "select 1", 2, 0)
            explicit = self.post("/query?format=tsv")
            self.assertEqual(explicit.text, response.text)
            self.assertEqual(explicit.headers["content-type"], response.headers["content-type"])
            response = self.post("/query?format=json")
            self.assertEqual(response.json(), {"columns": ["id"], "rows": [[1], [2]], "truncated": True})

    def test_specific_validation_errors(self):
        """无效请求参数返回带具体位置的纯文本错误"""
        for query, expected in [
            ("limit=0", "limit"),
            ("limit=3", "at most 2"),
            ("offset=-1", "offset"),
            ("format=text", "format"),
            ("format=xml", "format"),
        ]:
            with self.subTest(query=query):
                response = self.post("/query?" + query)
                self.assertEqual(response.status_code, 422)
                self.assertIn(expected, response.text)
                self.assertTrue(response.headers["content-type"].startswith("text/plain"))

    def test_request_limit_can_only_reduce_configured_cap(self):
        """请求可以缩小返回行数但不能突破配置上限"""
        with patch("app.api.query_result", return_value=QueryResult(["id"], [(1,)])) as query:
            for limit in (1, 2):
                response = self.post(f"/query?limit={limit}")
                self.assertEqual(response.status_code, 200)
                query.assert_called_with(self.session, "select 1", limit, 0)
            query.reset_mock()
            response = self.post("/query?limit=3")
            self.assertEqual(response.status_code, 422)
            query.assert_not_called()

    def test_empty_results_are_success_in_both_formats(self):
        """两种返回格式都将空结果表示为成功"""
        with patch("app.api.query_result", return_value=QueryResult(["id"], [])):
            self.assertEqual(self.post().text, "id")
            response = self.post("/query?format=json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["rows"], [])

    def test_health_removed_and_unknown_profile_reported(self):
        """未定义路由与未知环境均返回不可用错误"""
        self.assertEqual(self.client.get("/health").status_code, 404)
        self.app.dependency_overrides.clear()
        response = self.post()
        self.assertEqual(response.status_code, 404)
        self.assertIn("Unknown or disabled profile", response.text)

    def test_metadata_supports_tsv_and_json(self):
        """固定元数据接口默认返回 TSV 并支持显式格式"""
        profiles = self.client.get("/profiles")
        self.assertEqual(profiles.headers["content-type"], "text/tab-separated-values; charset=utf-8")
        self.assertEqual(self.client.get("/profiles?format=tsv").text, profiles.text)
        for path, function in [
            ("/schemas", "list_schemas"),
            ("/tables?schema=app", "list_tables"),
        ]:
            with self.subTest(path=path), patch("app.api." + function, return_value=QueryResult(["v"], [(1,)])):
                separator = "&" if "?" in path else "?"
                default = self.client.get("/profiles/test" + path)
                explicit = self.client.get("/profiles/test" + path + separator + "format=tsv")
                self.assertEqual(default.text, "v\n1")
                self.assertEqual(default.headers["content-type"], "text/tab-separated-values; charset=utf-8")
                self.assertEqual(explicit.text, default.text)
                response = self.client.get("/profiles/test" + path + separator + "format=json")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["rows"], [[1]])

    def test_ddl_remains_plain_text(self):
        """DDL 摘要继续返回纯文本而不是 TSV"""
        with patch("app.api.table_ddl_text", return_value="create table example"):
            response = self.client.get("/profiles/test/ddl?schema=app&table=example")
        self.assertEqual(response.text, "create table example")
        self.assertEqual(response.headers["content-type"], "text/plain; charset=utf-8")

    def test_count_and_explain_use_the_query_endpoint(self):
        """独立计数和执行计划入口不再提供"""
        self.assertEqual(self.post("/count").status_code, 404)
        self.assertEqual(self.post("/explain").status_code, 404)
