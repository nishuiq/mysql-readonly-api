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
    def __init__(self, profile: str) -> None:
        super().__init__(f"Unknown or disabled profile: {profile}")


class DatabaseConnectionError(Exception):
    pass


def mysql_error_number(exc: SQLAlchemyError) -> int | None:
    args = getattr(getattr(exc, "orig", None), "args", ())
    return args[0] if args and isinstance(args[0], int) else None


def database_error(exc: SQLAlchemyError) -> tuple[int, str]:
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
    # Do not stringify the SQLAlchemy wrapper: it includes SQL and bind values.
    return status, prefix + message


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        response = text_response(str(exc.detail), status_code=exc.status_code)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
        details = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            details.append(f"{location}: {error['msg']}")
        return text_response("Invalid request parameters: " + "; ".join(details), status_code=422)

    @app.exception_handler(UnknownProfileError)
    def unknown_profile_handler(request: Request, exc: UnknownProfileError) -> Response:
        return text_response(str(exc), status_code=404)

    @app.exception_handler(DatabaseConnectionError)
    def connection_handler(request: Request, exc: DatabaseConnectionError) -> Response:
        return text_response(str(exc), status_code=503)

    @app.exception_handler(UnicodeDecodeError)
    def unicode_decode_handler(request: Request, exc: UnicodeDecodeError) -> Response:
        return text_response("SQL body must be valid UTF-8.", status_code=400)

    @app.exception_handler(SQLAlchemyError)
    def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> Response:
        status, message = database_error(exc)
        logger.warning("Database request failed (status=%s, errno=%s)", status, mysql_error_number(exc))
        return text_response(message, status_code=status)

    @app.exception_handler(Exception)
    def exception_handler(request: Request, exc: Exception) -> Response:
        logger.error("Unhandled API error (%s)", type(exc).__name__)
        return text_response("Internal server error.", status_code=500)
