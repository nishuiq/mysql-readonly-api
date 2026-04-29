from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import URL
from sqlmodel import Session, create_engine

from app.config import settings


def mysql_url() -> URL:
    """根据配置生成 MySQL 连接 URL。"""
    return URL.create(
        drivername="mysql+pymysql",
        username=settings.mysql.username,
        password=settings.mysql.password,
        host=settings.mysql.host,
        port=settings.mysql.port,
    )


def mysql_connect_args() -> dict[str, object]:
    """根据配置生成 PyMySQL 连接参数。"""
    args: dict[str, object] = {
        "charset": settings.mysql.character_encoding,
        "use_unicode": settings.mysql.use_unicode,
    }
    if settings.mysql.use_ssl:
        args["ssl"] = {}
    args["init_command"] = mysql_init_command()
    return args


def mysql_init_command() -> str:
    """生成 MySQL session 初始化语句。"""
    items = [f"max_execution_time = {settings.query.timeout_ms}"]
    if settings.mysql.server_timezone:
        items.insert(0, f"time_zone = '{settings.mysql.server_timezone}'")
    return "SET " + ", ".join(items)


engine = create_engine(
    mysql_url(),
    connect_args=mysql_connect_args(),
    echo=settings.app.sql_log,
    pool_size=settings.mysql.pool.size,
    max_overflow=settings.mysql.pool.max_overflow,
    pool_timeout=settings.mysql.pool.timeout,
    pool_recycle=settings.mysql.pool.recycle,
    pool_pre_ping=settings.mysql.pool.pre_ping,
)


@contextmanager
def db_session() -> Iterator[Session]:
    """创建数据库会话。"""
    with Session(engine) as session:
        yield session
