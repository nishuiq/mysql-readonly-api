"""通过完整配置启动本地 MySQL 只读 REST 服务"""

from app.config import load_settings


def main() -> None:
    """读取启动配置并运行 Uvicorn 服务

    Raises:
        RuntimeError: 配置文件无法读取或配置不符合约束
    """
    import uvicorn

    settings = load_settings()
    enabled_profiles = ", ".join(settings.enabled_profiles) or "(none)"
    print(f"server={settings.server.host}:{settings.server.port} | enabled profiles={enabled_profiles}")
    uvicorn.run(
        "app.factory:create_app",
        factory=True,
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.server.reload,
    )


if __name__ == "__main__":
    main()
