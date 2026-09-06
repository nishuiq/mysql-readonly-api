"""将配置外的请求异常和数据库失败映射为清晰的纯文本响应"""

import logging
import ssl

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException

from app.text_format import text_response

logger = logging.getLogger("uvicorn.error")


class UnknownProfileError(Exception):
    """表示请求的环境不存在或未启用"""

    def __init__(self, profile: str) -> None:
        """创建未知环境异常

        Args:
            profile: 调用方请求的环境名称
        """
        super().__init__(f"Unknown or disabled profile: {profile}")


class DatabaseConnectionError(Exception):
    """表示连接建立后未满足服务要求的连接条件"""

    pass


def mysql_error_number(exc: SQLAlchemyError) -> int | None:
    """从 SQLAlchemy 包装异常中读取 MySQL 错误号

    Args:
        exc: 数据库层抛出的 SQLAlchemy 异常

    Returns:
        驱动提供的错误号，无法取得时为 None
    """
    args = getattr(getattr(exc, "orig", None), "args", ())
    return args[0] if args and isinstance(args[0], int) else None


def database_error(exc: SQLAlchemyError) -> tuple[int, str]:
    """根据数据库失败原因选择 HTTP 状态与错误提示

    Args:
        exc: 数据库异常，可包含驱动错误号及底层 TLS 错误

    Returns:
        HTTP 状态和纯文本提示，不附加完整 SQL、绑定参数或连接凭据
    """
    number = mysql_error_number(exc)
    prefix = f"MySQL {number}: " if number is not None else "Database: "
    if isinstance(exc, PoolTimeoutError):
        return 503, "Database connection pool is busy. Retry later."
    if number in {1205, 1317, 3024}:
        return 504, prefix + "Query timed out or was interrupted. Narrow the query and retry."
    original = getattr(getattr(exc, "orig", None), "original_exception", None)
    if isinstance(original, ssl.SSLCertVerificationError):
        return 503, prefix + "TLS certificate verification failed. Check CA trust, certificate validity and hostname."
    if isinstance(original, ssl.SSLError) or number == 2026:
        return 503, prefix + "TLS handshake failed. Check server TLS and certificate configuration."
    if number == 1045:
        return 503, prefix + "Authentication failed. Check profile credentials and authentication plugin."
    if number in {1129, 1130}:
        return 503, prefix + "Client host is blocked or not allowed. Check MySQL host access configuration."
    if number in {2002, 2003, 2005}:
        return 503, prefix + "Connection unavailable. Check server address, port, DNS and network."
    if number in {2006, 2013, 2055}:
        return 503, prefix + "Connection lost. Check server availability and network/socket timeouts."
    if number == 1060:
        return 400, prefix + "Duplicate result column name. Give each SELECT column a unique alias for paging/count."
    if number is None:
        return 500, "Database operation failed."
    status = 403 if number in {1044, 1142, 1143, 1227, 1370, 1792} else 404 if number in {1049, 1146, 1305} else 400
    args = getattr(exc.orig, "args", ())
    message = str(args[1]) if len(args) > 1 else "Query failed."
    # SQLAlchemy 包装异常会附带 SQL 和绑定值，只提取驱动消息
    return status, prefix + message


def register_exception_handlers(app: FastAPI) -> None:
    """为应用注册统一的纯文本异常响应

    Args:
        app: 需要注册异常处理器的 FastAPI 实例
    """

    @app.exception_handler(HTTPException)
    def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        """保留 HTTP 错误状态与响应头并输出文本

        Args:
            request: 框架传入的失败请求
            exc: 包含状态、消息及可选响应头的 HTTP 异常

        Returns:
            纯文本响应，保留 Allow 等契约响应头
        """
        response = text_response(str(exc.detail), status_code=exc.status_code)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
        """指出请求参数的校验位置和失败原因

        Args:
            request: 框架传入的失败请求
            exc: 框架收集的请求参数校验错误

        Returns:
            状态为 422 的文本提示，不回显原始请求输入
        """
        details = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            details.append(f"{location}: {error['msg']}")
        return text_response("Invalid request parameters: " + "; ".join(details), status_code=422)

    @app.exception_handler(UnknownProfileError)
    def unknown_profile_handler(request: Request, exc: UnknownProfileError) -> Response:
        """将未知或禁用环境统一映射为不可用对象

        Args:
            request: 框架传入的失败请求
            exc: 包含请求环境名称的异常

        Returns:
            状态为 404 的纯文本响应
        """
        return text_response(str(exc), status_code=404)

    @app.exception_handler(DatabaseConnectionError)
    def connection_handler(request: Request, exc: DatabaseConnectionError) -> Response:
        """报告未满足连接要求的数据库会话

        Args:
            request: 框架传入的失败请求
            exc: 服务生成的连接条件错误

        Returns:
            状态为 503 的纯文本响应
        """
        return text_response(str(exc), status_code=503)

    @app.exception_handler(UnicodeDecodeError)
    def unicode_decode_handler(request: Request, exc: UnicodeDecodeError) -> Response:
        """报告 SQL 请求体的字符编码错误

        Args:
            request: 框架传入的失败请求
            exc: UTF-8 解码失败异常

        Returns:
            状态为 400 的纯文本响应，不回显请求体
        """
        return text_response("SQL body must be valid UTF-8.", status_code=400)

    @app.exception_handler(SQLAlchemyError)
    def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> Response:
        """将数据库异常转换为可供调用方处理的响应

        Args:
            request: 框架传入的失败请求
            exc: SQLAlchemy 数据库异常

        Returns:
            按原因分类的错误响应，日志只记录状态和错误号
        """
        status, message = database_error(exc)
        logger.warning("Database request failed (status=%s, errno=%s)", status, mysql_error_number(exc))
        return text_response(message, status_code=status)

    @app.exception_handler(Exception)
    def exception_handler(request: Request, exc: Exception) -> Response:
        """为未分类的内部失败返回稳定提示

        Args:
            request: 框架传入的失败请求
            exc: 未被其他处理器分类的异常

        Returns:
            状态为 500 的文本响应，日志只记录异常类型
        """
        logger.error("Unhandled API error (%s)", type(exc).__name__)
        return text_response("Internal server error.", status_code=500)
