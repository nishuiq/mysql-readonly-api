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
        """请求省略行数时使用配置上限且两种格式保留截断状态"""
        with patch("app.api.query_result", return_value=QueryResult(["id"], [(1,), (2,)], True)) as query:
            response = self.post()
            self.assertEqual(response.text, "[truncated]\nid\n1\n2")
            query.assert_called_with(self.session, "select 1", 2, 0)
            response = self.post("/query?format=json")
            self.assertEqual(response.json(), {"columns": ["id"], "rows": [[1], [2]], "truncated": True})

    def test_specific_validation_errors(self):
        """无效请求参数返回带具体位置的纯文本错误"""
        for query, expected in [
            ("limit=0", "limit"),
            ("limit=3", "at most 2"),
            ("offset=-1", "offset"),
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

    def test_metadata_and_count_support_json(self):
        """元数据、计数和计划接口均支持 JSON 结果"""
        for method, path, function in [
            ("get", "/schemas", "list_schemas"),
            ("get", "/tables?schema=app", "list_tables"),
            ("post", "/count", "count_result"),
            ("post", "/explain", "explain_result"),
        ]:
            with self.subTest(path=path), patch("app.api." + function, return_value=QueryResult(["v"], [(1,)])):
                suffix = "&format=json" if "?" in path else "?format=json"
                response = (
                    self.post(path + suffix) if method == "post" else self.client.get("/profiles/test" + path + suffix)
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["rows"], [[1]])
