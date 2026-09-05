from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.config import Settings, load_settings
from app.database import Databases
from app.errors import register_exception_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.databases = Databases(settings)
        try:
            yield
        finally:
            app.state.databases.dispose()

    app = FastAPI(title=settings.app.name, lifespan=lifespan)
    app.state.settings = settings
    register_exception_handlers(app)
    app.include_router(router)
    return app
