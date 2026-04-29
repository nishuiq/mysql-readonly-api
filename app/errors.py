from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError

from app.text_format import text_response


def register_exception_handlers(app: FastAPI) -> None:
    """注册纯文本异常响应。"""

    @app.exception_handler(HTTPException)
    def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        """将 HTTP 异常转换成纯文本响应。"""
        return text_response(str(exc.detail), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    def validation_exception_handler(request: Request, exc: RequestValidationError) -> Response:
        """将参数校验异常转换成纯文本响应。"""
        return text_response(str(exc), status_code=422)

    @app.exception_handler(Exception)
    def exception_handler(request: Request, exc: Exception) -> Response:
        """将未处理异常转换成纯文本响应。"""
        return text_response(str(exc), status_code=500)
