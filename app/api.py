from typing import Annotated

from fastapi import APIRouter, Body, Query, Response

from app.config import settings
from app.ddl import table_ddl_text
from app.metadata import list_schemas, list_tables
from app.query import count_text, explain_text, query_text
from app.text_format import format_text_rows, text_response

router = APIRouter()


@router.get("/health", response_class=Response)
def health() -> Response:
    """检查服务是否启动。"""
    return text_response("OK")


@router.get("/profiles", response_class=Response)
def profiles() -> Response:
    """列出当前已启用的数据库 profile。"""
    rows = [(profile.name, profile.description) for profile in settings.enabled_profiles.values()]
    return text_response(format_text_rows(["name", "description"], rows))


@router.get("/profiles/{profile}/schemas", response_class=Response)
def schemas(profile: str) -> Response:
    """列出指定 profile 数据库里的 schema。"""
    return text_response(list_schemas(profile))


@router.get("/profiles/{profile}/tables", response_class=Response)
def tables(profile: str, schema: str = Query(...), keyword: str = Query("")) -> Response:
    """列出或搜索指定 schema 下的表。"""
    return text_response(list_tables(profile=profile, schema=schema, keyword=keyword))


@router.get("/profiles/{profile}/ddl", response_class=Response)
def ddl(profile: str, schema: str = Query(...), table: list[str] = Query(...)) -> Response:
    """查看一个或多个表的 IDEA 风格 DDL。"""
    return text_response(table_ddl_text(profile=profile, schema=schema, table=table))


@router.post("/profiles/{profile}/query", response_class=Response)
def query(
    profile: str,
    sql: Annotated[bytes, Body(media_type="text/plain")],
    offset: int = Query(0, ge=0),
    limit: int = Query(settings.query.default_limit, ge=1, le=settings.query.max_limit),
) -> Response:
    """执行 SELECT/WITH 查询，默认在 SQL 外层限制返回行数。"""
    return text_response(
        query_text(
            profile=profile,
            sql=sql.decode("utf-8"),
            limit=limit,
            offset=offset,
        )
    )


@router.post("/profiles/{profile}/count", response_class=Response)
def count(profile: str, sql: Annotated[bytes, Body(media_type="text/plain")]) -> Response:
    """统计 SELECT/WITH 查询结果数量。"""
    return text_response(count_text(profile=profile, sql=sql.decode("utf-8")))


@router.post("/profiles/{profile}/explain", response_class=Response)
def explain(profile: str, sql: Annotated[bytes, Body(media_type="text/plain")]) -> Response:
    """查看 SELECT/WITH 查询执行计划。"""
    return text_response(explain_text(profile=profile, sql=sql.decode("utf-8")))
