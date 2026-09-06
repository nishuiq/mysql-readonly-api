"""定义只读 REST 路由、请求参数和应用资源依赖"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from sqlmodel import Session

from app.config import Settings
from app.ddl import table_ddl_text
from app.executor import QueryResult
from app.metadata import list_schemas, list_tables
from app.query import count_result, explain_result, query_result
from app.text_format import OutputFormat, result_response, text_response

router = APIRouter()


def get_settings(request: Request) -> Settings:
    """读取当前请求所属应用的配置

    Args:
        request: 当前 HTTP 请求，用于定位应用实例

    Returns:
        启动时已经完整校验的配置快照
    """
    return request.app.state.settings


def get_session(profile: str, request: Request) -> Iterator[Session]:
    """在数据库请求期间提供指定环境的只读会话

    Args:
        profile: URL 中指定的环境名称
        request: 当前 HTTP 请求，用于定位应用独占的连接池

    Yields:
        已初始化的只读会话，请求结束时回滚事务并释放连接

    Raises:
        UnknownProfileError: 环境不存在或未启用
        SQLAlchemyError: 无法建立或取得数据库连接
    """
    with request.app.state.databases.session(profile) as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]
SqlBody = Annotated[bytes, Body(media_type="text/plain")]


def get_limit(settings: SettingsDep, limit: int | None = Query(None, ge=1)) -> int:
    """根据显式配置确定本次请求的返回行数

    Args:
        settings: 当前应用配置，其中 query.limit 是唯一行数上限
        limit: 请求校验后的正整数，为 None 时采用配置上限

    Returns:
        不超过配置上限的本次返回行数

    Raises:
        HTTPException: 请求行数超过配置上限，状态为 422
    """
    value = settings.query.limit if limit is None else limit
    if value > settings.query.limit:
        raise HTTPException(422, f"query.limit: must be at most {settings.query.limit}.")
    return value


LimitDep = Annotated[int, Depends(get_limit)]


@router.get("/profiles", response_class=Response)
def profiles(settings: SettingsDep, format: OutputFormat = "text") -> Response:
    """列出当前应用启用的数据库环境

    Args:
        settings: 当前应用配置
        format: 成功响应的表示形式，省略时使用 text

    Returns:
        包含环境名称与描述的结果响应，没有启用环境时返回空结果
    """
    rows = [(profile.name, profile.description) for profile in settings.enabled_profiles.values()]
    return result_response(QueryResult(["name", "description"], rows), format)


@router.get("/profiles/{profile}/schemas", response_class=Response)
def schemas(session: SessionDep, limit: LimitDep, format: OutputFormat = "text") -> Response:
    """列出当前环境中账号可见的业务 schema

    Args:
        session: 当前请求的只读会话
        limit: 已经校验的返回行数上限
        format: 成功响应的表示形式，省略时使用 text

    Returns:
        排除系统 schema 的结果响应，超过上限时标记截断

    Raises:
        SQLAlchemyError: 数据库元数据查询失败
    """
    return result_response(list_schemas(session, limit), format)


@router.get("/profiles/{profile}/tables", response_class=Response)
def tables(
    session: SessionDep,
    limit: LimitDep,
    schema: str = Query(..., min_length=1),
    keyword: str = "",
    format: OutputFormat = "text",
) -> Response:
    """按 schema 和关键字列出可见的表与视图

    Args:
        session: 当前请求的只读会话
        limit: 已经校验的返回行数上限
        schema: 要查询的 schema 名称
        keyword: 名称或注释的 LIKE 匹配片段，空字符串表示不筛选
        format: 成功响应的表示形式，省略时使用 text

    Returns:
        包含名称、对象类型、注释和估计行数的结果响应

    Raises:
        SQLAlchemyError: 数据库元数据查询失败
    """
    return result_response(list_tables(session, schema, keyword, limit), format)


@router.get("/profiles/{profile}/ddl", response_class=Response)
def ddl(session: SessionDep, schema: str = Query(..., min_length=1), table: list[str] = Query(...)) -> Response:
    """返回所选表或视图的紧凑结构描述

    Args:
        session: 当前请求的只读会话
        schema: 对象所属的 schema 名称
        table: 重复参数或逗号分隔的对象名称，含逗号的名称需使用反引号

    Returns:
        固定为文本的 DDL 摘要，不能作为完整备份或迁移脚本

    Raises:
        HTTPException: 对象名称参数无效或对象不存在、不可见
        SQLAlchemyError: 数据库元数据或视图源码查询失败
    """
    return text_response(table_ddl_text(session, schema, table))


@router.post("/profiles/{profile}/query", response_class=Response)
def query(
    session: SessionDep,
    sql: SqlBody,
    limit: LimitDep,
    offset: int = Query(0, ge=0),
    format: OutputFormat = "text",
) -> Response:
    """执行单条只读 SQL 并返回指定格式的有限结果集

    Args:
        session: 当前请求的只读会话
        sql: UTF-8 编码的原始 SQL 请求体
        limit: 已经校验的返回行数上限
        offset: SELECT/WITH 结果偏移量，SHOW 必须为零
        format: 成功响应的表示形式，省略时使用 text

    Returns:
        成功结果集，空结果仍成功，超出行数上限时标记截断

    Raises:
        UnicodeDecodeError: SQL 请求体不是有效 UTF-8
        HTTPException: SQL 不符合只读规则或 SHOW 使用非零偏移量
        SQLAlchemyError: SQL 执行失败
    """
    return result_response(query_result(session, sql.decode("utf-8"), limit, offset), format)


@router.post("/profiles/{profile}/count", response_class=Response)
def count(session: SessionDep, sql: SqlBody, format: OutputFormat = "text") -> Response:
    """统计提交的 SELECT/WITH 查询本身产生的行数

    Args:
        session: 当前请求的只读会话
        sql: UTF-8 编码的原始 SQL，内层 LIMIT 仍然生效
        format: 成功响应的表示形式，省略时使用 text

    Returns:
        包含 count 列和一行计数的响应

    Raises:
        UnicodeDecodeError: SQL 请求体不是有效 UTF-8
        HTTPException: SQL 不符合 SELECT/WITH 只读规则
        SQLAlchemyError: 计数查询执行失败
    """
    return result_response(count_result(session, sql.decode("utf-8")), format)


@router.post("/profiles/{profile}/explain", response_class=Response)
def explain(session: SessionDep, sql: SqlBody, limit: LimitDep, format: OutputFormat = "text") -> Response:
    """返回提交的 SELECT/WITH 查询执行计划

    Args:
        session: 当前请求的只读会话
        sql: UTF-8 编码的原始 SQL 请求体
        limit: 已经校验的计划结果行数上限
        format: 成功响应的表示形式，省略时使用 text

    Returns:
        MySQL EXPLAIN 的结果响应，超过上限时标记截断

    Raises:
        UnicodeDecodeError: SQL 请求体不是有效 UTF-8
        HTTPException: SQL 不符合 SELECT/WITH 只读规则
        SQLAlchemyError: 执行计划查询失败
    """
    return result_response(explain_result(session, sql.decode("utf-8"), limit), format)
