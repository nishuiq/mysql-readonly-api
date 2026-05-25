from app import create_app
from app.config import settings

app = create_app()


def main() -> None:
    """启动 uvicorn 服务。"""
    import uvicorn

    print(
        f"Active profile: {settings.profile} | "
        f"server={settings.server.host}:{settings.server.port} | "
        f"mysql={settings.mysql.host}:{settings.mysql.port}"
    )

    uvicorn.run(
        "main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.server.reload,
    )


if __name__ == "__main__":
    main()
