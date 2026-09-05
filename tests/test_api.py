import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api import get_session
from app.config import settings_from_dict
from app.executor import QueryResult
from app.factory import create_app


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(settings_from_dict({"query": {"default_limit": 2, "max_limit": 4}}))
        self.session = Mock(info={"sql_mode": "", "mysql_version": (5, 7, 44)})
        self.app.dependency_overrides[get_session] = lambda: self.session
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def post(self, path="/query", **kwargs):
        return self.client.post(
            "/profiles/test" + path, content="select 1", headers={"content-type": "text/plain"}, **kwargs
        )

    def test_query_formats_and_runtime_default(self):
        with patch("app.api.query_result", return_value=QueryResult(["id"], [(1,), (2,)], True)) as query:
            response = self.post()
            self.assertEqual(response.text, "[truncated]\nid\n1\n2")
            query.assert_called_with(self.session, "select 1", 2, 0)
            response = self.post("/query?format=json")
            self.assertEqual(response.json(), {"columns": ["id"], "rows": [[1], [2]], "truncated": True})

    def test_specific_validation_errors_and_removed_raw(self):
        for query, expected in [
            ("limit=0", "limit"),
            ("limit=5", "at most 4"),
            ("offset=-1", "offset"),
            ("format=xml", "format"),
            ("raw=true", "raw was removed"),
        ]:
            with self.subTest(query=query):
                response = self.post("/query?" + query)
                self.assertEqual(response.status_code, 422)
                self.assertIn(expected, response.text)
                self.assertTrue(response.headers["content-type"].startswith("text/plain"))

    def test_empty_results_are_success_in_both_formats(self):
        with patch("app.api.query_result", return_value=QueryResult(["id"], [])):
            self.assertEqual(self.post().text, "id")
            response = self.post("/query?format=json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["rows"], [])

    def test_health_removed_and_unknown_profile_reported(self):
        self.assertEqual(self.client.get("/health").status_code, 404)
        self.app.dependency_overrides.clear()
        response = self.post()
        self.assertEqual(response.status_code, 404)
        self.assertIn("Unknown or disabled profile", response.text)

    def test_metadata_and_count_support_json(self):
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
