"""协调只读 SQL 校验和结果分页"""

from sqlmodel import Session

from app.executor import QueryResult, run_query
from app.sql_guard import validate_sql


def query_result(session: Session, sql: str, limit: int, offset: int) -> QueryResult:
    """执行单条只读 SQL 并限制返回结果

    Args:
        session: 附带实际 SQL mode 的只读会话
        sql: 调用方提交的单条 SQL，已有最外层 LIMIT 时保持原文
        limit: 已经校验的返回行数上限
        offset: 原 SQL 结果的非负偏移量

    Returns:
        从偏移位置开始的有限结果，读取到额外行时标记截断

    Raises:
        HTTPException: SQL 不符合只读规则或最外层 LIMIT 超过上限
        SQLAlchemyError: 数据库执行失败
    """
    validated = validate_sql(sql, session.info["sql_mode"])
    if validated.statement in {"select", "with"} and validated.limit is None:
        return run_query(session, f"{validated.sql}\nLIMIT {limit + 1} OFFSET {offset}", limit=limit, offset=0)
    return run_query(session, validated.sql, limit=limit, offset=offset)
