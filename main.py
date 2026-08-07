from app import create_app
from app.config import settings

app = create_app()


def main() -> None:
    """启动 uvicorn 服务。"""
    import uvicorn

    enabled_profiles = ", ".join(settings.enabled_profiles) or "(none)"
    print(f"server={settings.server.host}:{settings.server.port} | enabled profiles={enabled_profiles}")

    uvicorn.run(
        "main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.server.reload,
    )


if __name__ == "__main__":
    main()
