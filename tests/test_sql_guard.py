"""覆盖 MySQL 字符边界与只读 SQL 检查"""

import unittest

from fastapi import HTTPException

from app.sql_guard import clean_select_sql, count_sql, paged_sql, validate_sql


class SqlGuardTest(unittest.TestCase):
    """覆盖 MySQL 字符边界与只读 SQL 检查"""

    def test_preserves_strings_identifiers_and_functions(self):
        """普通读取函数和字段字面量不会被误判为写操作"""
        for sql in [
            "select replace('create; # -- /* @x', 'a', 'b')",
            "select INSERT('abcd', 2, 1, 'Z'), TRUNCATE(1.23, 1), 1 as start",
            "select t.update, t.create from t",
            "select `;`, `@`, `:=`, `sleep` from t",
            "select ':name', '%(name)s', '100%', '\\\\n', '\\n'",
            "select `update`, `a;b`, `a``b` from `set`",
            """select 'a'';b', "a"";b" """,
            "show create procedure app.proc",
            "show create event app.event",
            "select @@session.sql_mode, @@session.transaction_read_only",
        ]:
            with self.subTest(sql=sql):
                self.assertEqual(validate_sql(sql).sql, sql.strip())

    def test_ordinary_comments_and_delimiter(self):
        """普通注释可用且只移除语句末尾的分号"""
        sql = "/* header */ select 1; -- last comment"
        validated = validate_sql(sql)
        self.assertEqual(validated.statement, "select")
        self.assertEqual(validated.sql, "/* header */ select 1 -- last comment")
        self.assertEqual(validate_sql("# comment\nselect 1;").sql, "# comment\nselect 1")
        self.assertEqual(validate_sql("select 1--2").sql, "select 1--2")

    def test_statement_type_ignores_comments_and_quoted_content(self):
        """语句分派只取未引用的首个关键字且保留后续文本"""
        for sql, statement in [
            ("/* SHOW */ SeLeCt 'with; show' AS `select`; -- keep", "select"),
            ("# SELECT\nWITH q AS (SELECT 1) SELECT * FROM q;", "with"),
            ("-- WITH\nShOw CREATE TABLE `select`; # keep", "show"),
        ]:
            with self.subTest(sql=sql):
                self.assertEqual(validate_sql(sql).statement, statement)
        for sql in ["`select` 1", "'select' 1", '"select" 1', ";"]:
            with self.subTest(sql=sql), self.assertRaises(HTTPException):
                validate_sql(sql)

    def test_rejects_executable_comments_and_multiple_statements(self):
        """多语句、可执行注释和不完整词法边界被拒绝"""
        for sql in [
            "select 1; select 2",
            "select 1;;",
            "select /*!50000 sleep(1) */ 1",
            "select /*+ MAX_EXECUTION_TIME(0) */ 1",
            "select /*M! sleep(1) */ 1",
            "select 1 /* missing",
            "select 'missing",
            "-- no query",
        ]:
            with self.subTest(sql=sql), self.assertRaises(HTTPException):
                validate_sql(sql)

    def test_read_only_guards_include_show_expressions(self):
        """只读规则也覆盖 SHOW 表达式与带引用的函数调用"""
        for sql in [
            "insert into t values (1)",
            "with x as (select 1) delete from t",
            "select * from t for update",
            "select * from t for share",
            "select * from t lock in share mode",
            "set transaction read write",
            "call proc()",
            "select * from t into outfile '/tmp/test'",
            "select load_file('/tmp/test')",
            "select sleep /* comment */ (1)",
            "select `sleep`(1)",
            "select `load_file`('/tmp/test')",
            "select benchmark(10, md5('a'))",
            "select get_lock('x',1)",
            "select @x",
            "select 1 into @x",
            "select @x:=1",
            "show tables where sleep(1)=0",
            "show tables where @x:=1",
        ]:
            with self.subTest(sql=sql), self.assertRaises(HTTPException):
                validate_sql(sql)

    def test_sql_mode_controls_quote_boundaries(self):
        """词法边界遵循实际 SQL mode"""
        sql = r"select 'a\'; select 2 -- '"
        self.assertEqual(validate_sql(sql).sql, sql)
        with self.assertRaises(HTTPException):
            validate_sql(sql, "NO_BACKSLASH_ESCAPES")
        quoted_identifier = 'select "a\\"; select 2 -- "'
        self.assertEqual(validate_sql(quoted_identifier).sql, quoted_identifier)
        with self.assertRaises(HTTPException):
            validate_sql(quoted_identifier, "ANSI_QUOTES")
        with self.assertRaises(HTTPException):
            validate_sql('select "sleep"(1)', "ANSI_QUOTES")

    def test_paging_and_count_keep_inner_limit_and_trailing_comment(self):
        """外层查询保留内部 LIMIT 且末尾行注释不会吞掉包装语句"""
        sql = validate_sql("select 1 limit 1 -- keep").sql
        self.assertEqual(
            paged_sql(sql, 5, 10), "SELECT *\nFROM (\nselect 1 limit 1 -- keep\n) AS _codex_query\nLIMIT 6 OFFSET 10"
        )
        self.assertIn("-- keep\n)", count_sql(sql))
        with self.assertRaises(HTTPException):
            clean_select_sql("show tables")
