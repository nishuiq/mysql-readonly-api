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
    return request.app.state.settings


def get_session(profile: str, request: Request) -> Iterator[Session]:
    with request.app.state.databases.session(profile) as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]
SqlBody = Annotated[bytes, Body(media_type="text/plain")]


def get_limit(settings: SettingsDep, limit: int | None = Query(None, ge=1)) -> int:
    value = settings.query.default_limit if limit is None else limit
    if value > settings.query.max_limit:
        raise HTTPException(422, f"query.limit: must be at most {settings.query.max_limit}.")
    return value


LimitDep = Annotated[int, Depends(get_limit)]


@router.get("/profiles", response_class=Response)
def profiles(settings: SettingsDep, format: OutputFormat = "text") -> Response:
    rows = [(profile.name, profile.description) for profile in settings.enabled_profiles.values()]
    return result_response(QueryResult(["name", "description"], rows), format)


@router.get("/profiles/{profile}/schemas", response_class=Response)
def schemas(session: SessionDep, limit: LimitDep, format: OutputFormat = "text") -> Response:
    return result_response(list_schemas(session, limit), format)


@router.get("/profiles/{profile}/tables", response_class=Response)
def tables(
    session: SessionDep,
    limit: LimitDep,
    schema: str = Query(..., min_length=1),
    keyword: str = "",
    format: OutputFormat = "text",
) -> Response:
    return result_response(list_tables(session, schema, keyword, limit), format)


@router.get("/profiles/{profile}/ddl", response_class=Response)
def ddl(session: SessionDep, schema: str = Query(..., min_length=1), table: list[str] = Query(...)) -> Response:
    return text_response(table_ddl_text(session, schema, table))


@router.post("/profiles/{profile}/query", response_class=Response)
def query(
    request: Request,
    session: SessionDep,
    sql: SqlBody,
    limit: LimitDep,
    offset: int = Query(0, ge=0),
    format: OutputFormat = "text",
) -> Response:
    if "raw" in request.query_params:
        raise HTTPException(422, "raw was removed; use format=text or format=json (supports multiple rows/columns).")
    return result_response(query_result(session, sql.decode("utf-8"), limit, offset), format)


@router.post("/profiles/{profile}/count", response_class=Response)
def count(session: SessionDep, sql: SqlBody, format: OutputFormat = "text") -> Response:
    return result_response(count_result(session, sql.decode("utf-8")), format)


@router.post("/profiles/{profile}/explain", response_class=Response)
def explain(session: SessionDep, sql: SqlBody, limit: LimitDep, format: OutputFormat = "text") -> Response:
    return result_response(explain_result(session, sql.decode("utf-8"), limit), format)
