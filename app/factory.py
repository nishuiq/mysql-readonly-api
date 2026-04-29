from fastapi import FastAPI

from app.api import router
from app.config import settings
from app.errors import register_exception_handlers


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""
    app = FastAPI(title=settings.app.name)
    register_exception_handlers(app)
    app.include_router(router)
    return app
