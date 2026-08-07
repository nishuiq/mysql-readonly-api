from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

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


def mysql_connect_args(mysql: MysqlConfig, query: QueryConfig) -> dict[str, object]:
    """根据配置生成 PyMySQL 连接参数。"""
    args: dict[str, object] = {
        "charset": mysql.character_encoding,
        "use_unicode": mysql.use_unicode,
    }
    if mysql.use_ssl:
        args["ssl"] = {}
    args["init_command"] = mysql_init_command(mysql, query)
    return args


def mysql_init_command(mysql: MysqlConfig, query: QueryConfig) -> str:
    """生成 MySQL session 初始化语句。"""
    items = [f"max_execution_time = {query.timeout_ms}"]
    if mysql.server_timezone:
        items.insert(0, f"time_zone = '{mysql.server_timezone}'")
    return "SET " + ", ".join(items)


def create_mysql_engine(mysql: MysqlConfig) -> Engine:
    """为单个 profile 创建惰性 MySQL 连接池。"""
    return create_engine(
        mysql_url(mysql),
        connect_args=mysql_connect_args(mysql, settings.query),
        echo=settings.app.sql_log,
        pool_size=mysql.pool.size,
        max_overflow=mysql.pool.max_overflow,
        pool_timeout=mysql.pool.timeout,
        pool_recycle=mysql.pool.recycle,
        pool_pre_ping=mysql.pool.pre_ping,
    )


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
