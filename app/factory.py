"""在启动时创建应用并管理其连接池生命周期"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.config import Settings, load_settings
from app.database import Databases
from app.errors import register_exception_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建具备显式配置和独立连接池生命周期的应用

    Args:
        settings: 已经校验的配置，为 None 时从 config.yaml 加载完整配置文件

    Returns:
        注册路由与异常处理器的应用，连接池在生命周期启动时创建

    Raises:
        RuntimeError: 从文件加载时配置缺失或不符合约束
    """
    settings = settings if settings is not None else load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """在应用运行期间持有并最终释放连接池

        Args:
            app: 当前进入或退出生命周期的应用实例

        Yields:
            应用已完成连接池准备的运行阶段，退出时释放全部连接池

        Raises:
            OSError: 环境 CA 文件无效，无法建立连接参数
        """
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
