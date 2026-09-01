from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import URL, Engine
from sqlmodel import Session, create_engine

from app.config import MysqlConfig, ProfileConfig, QueryConfig, settings
from app.errors import UnknownProfileError


def mysql_url(mysql: MysqlConfig) -> URL:
    """根据配置生成 MySQL 连接 URL。"""
    return URL.create(
        drivername="mysql+pymysql",
        username=mysql.username,
        password=mysql.password,
        host=mysql.host,
        port=mysql.port,
    )


def mysql_connect_args(mysql: MysqlConfig) -> dict[str, object]:
    """根据配置生成 PyMySQL 连接参数。"""
    args: dict[str, object] = {
        "charset": mysql.character_encoding,
        "use_unicode": mysql.use_unicode,
    }
    if mysql.use_ssl:
        args["ssl"] = {}
    return args


def initialize_mysql_session(
    dbapi_connection: Any,
    mysql: MysqlConfig,
    query: QueryConfig,
) -> None:
    """在物理连接建立时初始化 MySQL session。"""
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
        if mysql.server_timezone:
            cursor.execute("SET SESSION time_zone = %s", (mysql.server_timezone,))
        cursor.execute("SET SESSION max_execution_time = %s", (query.timeout_ms,))


def create_mysql_engine(mysql: MysqlConfig) -> Engine:
    """为单个 profile 创建惰性 MySQL 连接池。"""
    engine = create_engine(
        mysql_url(mysql),
        connect_args=mysql_connect_args(mysql),
        echo=settings.app.sql_log,
        pool_size=mysql.pool.size,
        max_overflow=mysql.pool.max_overflow,
        pool_timeout=mysql.pool.timeout,
        pool_recycle=mysql.pool.recycle,
        pool_pre_ping=mysql.pool.pre_ping,
    )

    def initialize_connection(dbapi_connection: Any, _connection_record: Any) -> None:
        initialize_mysql_session(dbapi_connection, mysql, settings.query)

    event.listen(engine, "connect", initialize_connection)
    return engine


@dataclass(frozen=True)
class ProfileDatabase:
    """一个已启用 profile 的配置和连接池。"""

    profile: ProfileConfig
    engine: Engine


profile_databases = {
    name: ProfileDatabase(profile=profile, engine=create_mysql_engine(profile.mysql))
    for name, profile in settings.enabled_profiles.items()
}


def profile_database(profile: str) -> ProfileDatabase:
    """读取已启用 profile；禁用和不存在均按未知处理。"""
    database = profile_databases.get(profile)
    if database is None:
        raise UnknownProfileError(profile)
    return database


@contextmanager
def db_session(profile: str) -> Iterator[Session]:
    """为指定 profile 创建数据库会话。"""
    database = profile_database(profile)
    with Session(database.engine) as session:
        session.info["zero_datetime_behavior"] = database.profile.mysql.zero_datetime_behavior
        yield session


def dispose_engines() -> None:
    """关闭所有 profile 的连接池。"""
    for database in profile_databases.values():
        database.engine.dispose()
