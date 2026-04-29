from fastapi import APIRouter, Query, Request, Response

from app.config import settings
from app.ddl import table_ddl_text
from app.metadata import list_schemas, list_tables
from app.query import count_text, query_text
from app.text_format import text_response

router = APIRouter()


@router.get("/health", response_class=Response)
def health() -> Response:
    """检查服务是否启动。"""
    return text_response("OK")


@router.get("/schemas", response_class=Response)
def schemas() -> Response:
    """列出当前数据库里的 schema。"""
    return text_response(list_schemas())


@router.get("/tables", response_class=Response)
def tables(schema: str = Query(...), keyword: str = Query("")) -> Response:
    """列出或搜索指定 schema 下的表。"""
    return text_response(list_tables(schema=schema, keyword=keyword))


@router.get("/ddl", response_class=Response)
def ddl(schema: str = Query(...), table: list[str] = Query(...)) -> Response:
    """查看一个或多个表的 IDEA 风格 DDL。"""
    return text_response(table_ddl_text(schema=schema, table=table))


@router.post("/query", response_class=Response)
async def query(
    request: Request,
    offset: int = Query(settings.query.default_offset, ge=0),
    limit: int = Query(settings.query.default_limit, ge=1, le=settings.query.max_limit),
) -> Response:
    """执行 SELECT/WITH 查询，默认在 SQL 外层限制返回行数。"""
    sql = await request.body()
    return text_response(
        query_text(
            sql=sql.decode("utf-8"),
            limit=limit,
            offset=offset,
        )
    )


@router.post("/count", response_class=Response)
async def count(request: Request) -> Response:
    """统计 SELECT/WITH 查询结果数量。"""
    sql = await request.body()
    return text_response(count_text(sql=sql.decode("utf-8")))
