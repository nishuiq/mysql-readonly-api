from app.config import load_settings


def main() -> None:
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
