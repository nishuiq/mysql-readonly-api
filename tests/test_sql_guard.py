"""覆盖只读 SQL、语句边界和最外层行数限制"""

import unittest

from fastapi import HTTPException

from app.sql_guard import validate_sql


class SqlGuardTest(unittest.TestCase):
    """覆盖用户 SQL 的可执行范围"""

    def test_read_queries_keep_original_text_and_literal_characters(self):
        """只读查询原文和字符串中的分号、注释符保持不变"""
        for sql in [
            "  SELECT ':name', '%(name)s', 'create; # -- /* @x'  ",
            "SELECT INSERT('abcd', 2, 1, 'Z'), REPLACE('a;b', ';', '#'), TRUNCATE(1.23, 1)",
            "SELECT `;`, `@`, `:=`, `sleep` FROM `set`",
            "SELECT 1--2",
            "SELECT @@session.sql_mode, @@session.transaction_read_only",
            "SELECT COUNT(*) FROM app.orders",
            "SHOW CREATE PROCEDURE app.proc",
            "SHOW GRANTS FOR CURRENT_USER()",
            "EXPLAIN SELECT * FROM app.orders",
            "EXPLAIN FORMAT=JSON SELECT * FROM app.orders LIMIT 20",
            "WITH q AS (SELECT 1 AS id) SELECT id FROM q",
        ]:
            with self.subTest(sql=sql):
                self.assertEqual(validate_sql(sql).sql, sql)

    def test_comments_and_statement_semicolons_are_rejected(self):
        """语句分号和各类 SQL 注释均在执行前拒绝"""
        for sql in [
            "SELECT 1;",
            "SELECT 1; SELECT 2",
            "SELECT 1 # note",
            "SELECT 1 -- note",
            "SHOW VARIABLES--\x7f note",
            "SELECT 1 /* ordinary */",
            "SELECT 1 /*!50000 + SLEEP(1) */",
            "SELECT /*+ MAX_EXECUTION_TIME(0) */ 1",
            "SELECT 1 /*M! + SLEEP(1) */",
            "SELECT 'missing",
        ]:
            with self.subTest(sql=sql), self.assertRaises(HTTPException):
                validate_sql(sql)

    def test_unsafe_statements_functions_and_explain_analyze_are_rejected(self):
        """写操作、事务切换、危险函数和执行型计划均被拒绝"""
        for sql in [
            "INSERT INTO app.t VALUES (1)",
            "WITH q AS (SELECT 1) DELETE FROM app.t",
            "SET SESSION TRANSACTION READ WRITE",
            "CALL app.proc()",
            "SELECT * FROM app.t FOR UPDATE",
            "SELECT * FROM app.t FOR SHARE",
            "SELECT * FROM app.t LOCK IN SHARE MODE",
            "SELECT * FROM app.t INTO OUTFILE '/tmp/test'",
            "SELECT `sleep`(1)",
            "SELECT GET_LOCK('x', 1)",
            "SELECT WAIT_FOR_EXECUTED_GTID_SET('a:1', 1)",
            "SELECT @x:=1",
            "SHOW TABLES WHERE SLEEP(1)=0",
            "EXPLAIN DELETE FROM app.t",
            "EXPLAIN ANALYZE SELECT * FROM app.t",
            "eXpLaIn AnAlYzE SELECT 1",
        ]:
            with self.subTest(sql=sql), self.assertRaises(HTTPException):
                validate_sql(sql)

    def test_only_outer_limit_row_count_is_capped(self):
        """最外层 LIMIT 最多 5000 行且偏移和内层限制不受影响"""
        accepted = [
            "SELECT * FROM app.t LIMIT 5000",
            "SELECT * FROM app.t LIMIT 6000, 20",
            "SELECT * FROM app.t LIMIT 20 OFFSET 6000",
            "SELECT * FROM (SELECT * FROM app.t LIMIT 6000) q",
            "SELECT * FROM (SELECT * FROM app.t LIMIT 6000) q LIMIT 20",
            "SELECT id FROM app.a UNION ALL SELECT id FROM app.b LIMIT 5000",
            "EXPLAIN SELECT * FROM app.t LIMIT 5000",
            "SHOW WARNINGS LIMIT 5000",
            "SELECT 1 LIMIT 0",
        ]
        rejected = [
            "SELECT * FROM app.t LIMIT 5001",
            "SELECT * FROM app.t LIMIT 20, 5001",
            "SELECT * FROM app.t LIMIT 5001 OFFSET 20",
            "SELECT id FROM app.a UNION ALL SELECT id FROM app.b LIMIT 5001",
            "EXPLAIN SELECT * FROM app.t LIMIT 5001",
            "SHOW WARNINGS LIMIT 5001",
        ]
        for sql in accepted:
            with self.subTest(sql=sql):
                self.assertEqual(validate_sql(sql).sql, sql)
        for sql in rejected:
            with self.subTest(sql=sql), self.assertRaisesRegex(HTTPException, "at most 5000"):
                validate_sql(sql)

    def test_existing_mode_boundaries_protect_comments_and_semicolons(self):
        """既有会话引用规则阻止注释或语句分号藏在字符串边界后"""
        sql = r"SELECT '0\' /*!50000 + SLEEP(1) */ #'"
        self.assertEqual(validate_sql(sql).sql, sql)
        with self.assertRaises(HTTPException):
            validate_sql(sql, "NO_BACKSLASH_ESCAPES")
        with self.assertRaises(HTTPException):
            validate_sql('SELECT "sleep"(1)', "ANSI_QUOTES")
