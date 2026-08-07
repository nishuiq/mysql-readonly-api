from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.config import settings
from app.database import dispose_engines
from app.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """在服务关闭时释放所有数据库连接池。"""
    yield
    dispose_engines()


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""
    app = FastAPI(title=settings.app.name, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(router)
    return app
