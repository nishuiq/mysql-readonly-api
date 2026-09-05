import unittest

from fastapi import HTTPException

from app.sql_guard import clean_select_sql, clean_sql, count_sql, first_word, paged_sql


class SqlGuardTest(unittest.TestCase):
    def test_preserves_strings_identifiers_and_functions(self):
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
                self.assertEqual(clean_sql(sql), sql.strip())

    def test_ordinary_comments_and_delimiter(self):
        sql = "/* header */ select 1; -- last comment"
        self.assertEqual(first_word(sql), "select")
        self.assertEqual(clean_sql(sql), "/* header */ select 1 -- last comment")
        self.assertEqual(clean_sql("# comment\nselect 1;"), "# comment\nselect 1")
        self.assertEqual(clean_sql("select 1--2"), "select 1--2")

    def test_rejects_executable_comments_and_multiple_statements(self):
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
                clean_sql(sql)

    def test_read_only_guards_include_show_expressions(self):
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
                clean_sql(sql)

    def test_sql_mode_controls_quote_boundaries(self):
        sql = r"select 'a\'; select 2 -- '"
        self.assertEqual(clean_sql(sql), sql)
        with self.assertRaises(HTTPException):
            clean_sql(sql, "NO_BACKSLASH_ESCAPES")
        quoted_identifier = 'select "a\\"; select 2 -- "'
        self.assertEqual(clean_sql(quoted_identifier), quoted_identifier)
        with self.assertRaises(HTTPException):
            clean_sql(quoted_identifier, "ANSI_QUOTES")
        with self.assertRaises(HTTPException):
            clean_sql('select "sleep"(1)', "ANSI_QUOTES")

    def test_paging_and_count_keep_inner_limit_and_trailing_comment(self):
        sql = clean_sql("select 1 limit 1 -- keep")
        self.assertEqual(
            paged_sql(sql, 5, 10), "SELECT *\nFROM (\nselect 1 limit 1 -- keep\n) AS _codex_query\nLIMIT 6 OFFSET 10"
        )
        self.assertIn("-- keep\n)", count_sql(sql))
        with self.assertRaises(HTTPException):
            clean_select_sql("show tables")
