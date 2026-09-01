import logging

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.text_format import text_response


logger = logging.getLogger("uvicorn.error")


class UnknownProfileError(Exception):
    """请求的 profile 不存在或未启用。"""

    def __init__(self, profile: str) -> None:
        super().__init__(f"Unknown profile: {profile}")


def register_exception_handlers(app: FastAPI) -> None:
    """注册纯文本异常响应。"""

    @app.exception_handler(HTTPException)
    def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        """将 HTTP 异常转换成纯文本响应。"""
        return text_response(str(exc.detail), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
        """将参数校验异常转换成纯文本响应。"""
        return text_response(
            "Invalid request parameters.",
            status_code=422,
        )

    @app.exception_handler(UnknownProfileError)
    def unknown_profile_handler(request: Request, exc: UnknownProfileError) -> Response:
        """隐藏禁用 profile，并按不存在处理。"""
        return text_response(
            str(exc),
            status_code=404,
        )

    @app.exception_handler(UnicodeDecodeError)
    def unicode_decode_handler(request: Request, exc: UnicodeDecodeError) -> Response:
        """拒绝非 UTF-8 SQL 请求体。"""
        return text_response(
            "SQL body must be valid UTF-8.",
            status_code=400,
        )

    @app.exception_handler(SQLAlchemyError)
    def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> Response:
        """隐藏驱动异常、SQL 和连接信息，只返回稳定错误。"""
        logger.error("Database query failed", exc_info=(type(exc), exc, exc.__traceback__))
        if mysql_error_number(exc) in {1205, 1317, 3024}:
            return text_response(
                "Database query timed out.",
                status_code=504,
            )
        return text_response(
            "Database query failed.",
            status_code=400,
        )

    @app.exception_handler(Exception)
    def exception_handler(request: Request, exc: Exception) -> Response:
        """隐藏未处理异常的内部实现细节。"""
        logger.error("Unhandled API error", exc_info=(type(exc), exc, exc.__traceback__))
        return text_response(
            "Internal server error.",
            status_code=500,
        )


def mysql_error_number(exc: SQLAlchemyError) -> int | None:
    """读取 SQLAlchemy 包装的 MySQL errno。"""
    original = getattr(exc, "orig", None)
    args = getattr(original, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None
