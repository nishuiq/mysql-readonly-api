from __future__ import annotations

import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import URL, Engine
from sqlmodel import Session, create_engine

from app.config import MysqlConfig, QueryConfig, Settings
from app.errors import DatabaseConnectionError, UnknownProfileError


def mysql_url(mysql: MysqlConfig) -> URL:
    return URL.create(
        "mysql+pymysql", username=mysql.username, password=mysql.password, host=mysql.host, port=mysql.port
    )


def mysql_connect_args(mysql: MysqlConfig) -> dict[str, object]:
    args: dict[str, object] = {
        "charset": mysql.character_encoding,
        "use_unicode": mysql.use_unicode,
        "connect_timeout": mysql.connect_timeout,
        "read_timeout": mysql.read_timeout,
        "write_timeout": mysql.write_timeout,
        "local_infile": False,
    }
    if mysql.use_ssl:
        args["ssl"] = ssl.create_default_context(cafile=mysql.ssl_ca)
    else:
        args["ssl_disabled"] = True
    return args


def initialize_mysql_session(dbapi_connection: Any, mysql: MysqlConfig, query: QueryConfig) -> str:
    """初始化物理连接，并读取词法检查和 DDL 引用需要的 SQL mode。"""
    if mysql.use_ssl and not getattr(dbapi_connection, "_secure", False):
        # PyMySQL may fall back to plaintext when the server lacks CLIENT.SSL.
        raise DatabaseConnectionError("TLS is required but the MySQL connection is not encrypted.")
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
        if mysql.server_timezone:
            cursor.execute("SET SESSION time_zone = %s", (mysql.server_timezone,))
        cursor.execute("SET SESSION max_execution_time = %s", (query.timeout_ms,))
        cursor.execute("SELECT @@SESSION.sql_mode")
        value = cursor.fetchone()[0]
        return value.decode("ascii") if isinstance(value, bytes) else str(value)


def create_mysql_engine(mysql: MysqlConfig, settings: Settings) -> Engine:
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

    def initialize_connection(dbapi_connection: Any, record: Any) -> None:
        record.info["sql_mode"] = initialize_mysql_session(dbapi_connection, mysql, settings.query)

    event.listen(engine, "connect", initialize_connection)
    return engine


class Databases:
    """应用独占的惰性连接池；无模块级配置或连接资源。"""

    def __init__(self, settings: Settings) -> None:
        self.engines: dict[str, Engine] = {}
        try:
            for name, profile in settings.enabled_profiles.items():
                self.engines[name] = create_mysql_engine(profile.mysql, settings)
        except Exception:
            self.dispose()
            raise

    @contextmanager
    def session(self, profile: str) -> Iterator[Session]:
        engine = self.engines.get(profile)
        if engine is None:
            raise UnknownProfileError(profile)
        with Session(engine) as session:
            connection = session.connection()
            session.info["sql_mode"] = connection.info["sql_mode"]
            session.info["mysql_version"] = engine.dialect.server_version_info
            yield session

    def dispose(self) -> None:
        for engine in self.engines.values():
            engine.dispose()
