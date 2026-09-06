"""管理每个应用的 MySQL 连接池与只读会话"""

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
    """构造不含默认 schema 的 MySQL 连接地址

    Args:
        mysql: 已经校验的数据源配置

    Returns:
        由 SQLAlchemy 处理凭据转义的连接地址
    """
    return URL.create(
        "mysql+pymysql", username=mysql.username, password=mysql.password, host=mysql.host, port=mysql.port
    )


def mysql_connect_args(mysql: MysqlConfig) -> dict[str, object]:
    """构造显式的驱动连接参数与 TLS 上下文

    Args:
        mysql: 完整的数据源配置，TLS 开启时要求可信证书与匹配的主机名

    Returns:
        传给 PyMySQL 的连接参数，始终关闭 LOCAL INFILE

    Raises:
        OSError: 配置的 CA 文件无法读取或不能构建 TLS 上下文
    """
    args: dict[str, object] = {
        "charset": mysql.character_encoding,
        "use_unicode": mysql.use_unicode,
        "connect_timeout": mysql.connect_timeout,
        "read_timeout": mysql.io_timeout,
        "write_timeout": mysql.io_timeout,
        "local_infile": False,
    }
    if mysql.use_ssl:
        args["ssl"] = ssl.create_default_context(cafile=mysql.ssl_ca)
    else:
        args["ssl_disabled"] = True
    return args


def initialize_mysql_session(dbapi_connection: Any, mysql: MysqlConfig, query: QueryConfig) -> str:
    """初始化物理连接的只读状态并读取 SQL mode

    Args:
        dbapi_connection: 新建立的 PyMySQL 物理连接
        mysql: 所属环境的连接配置
        query: 显式的查询执行时间和行数配置

    Returns:
        会话实际使用的 SQL mode，供 SQL 词法检查与 DDL 引用使用

    Raises:
        DatabaseConnectionError: 要求 TLS 但驱动实际建立了明文连接
        pymysql.Error: 会话初始化或 SQL mode 查询失败
    """
    if mysql.use_ssl and not getattr(dbapi_connection, "_secure", False):
        # 服务端未声明 CLIENT.SSL 时，PyMySQL 可能退回明文连接
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
    """为一个环境建立应用独占的惰性连接池

    Args:
        mysql: 当前环境的完整连接配置
        settings: 应用配置，提供日志开关和查询超时

    Returns:
        注册了物理连接初始化钩子的引擎，尚未连接数据库

    Raises:
        OSError: 无法读取 CA 文件或建立 TLS 上下文
    """
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
        """为新物理连接设置只读策略并缓存 SQL mode

        Args:
            dbapi_connection: 本次新建的驱动连接
            record: 连接池记录，其 info 随物理连接保存词法模式

        Raises:
            DatabaseConnectionError: 要求 TLS 但实际连接未加密
            pymysql.Error: 会话初始化失败
        """
        record.info["sql_mode"] = initialize_mysql_session(dbapi_connection, mysql, settings.query)

    event.listen(engine, "connect", initialize_connection)
    return engine


class Databases:
    """表示一个应用独占的环境连接池集合"""

    def __init__(self, settings: Settings) -> None:
        """创建全部启用环境的惰性连接池

        Args:
            settings: 完整配置快照，只有启用环境会创建连接池

        Raises:
            OSError: 某个环境的 CA 配置不可读取或无效，已创建的池会先释放
        """
        self.engines: dict[str, Engine] = {}
        """当前应用独占的启用环境连接池，随应用关闭释放"""
        try:
            for name, profile in settings.enabled_profiles.items():
                self.engines[name] = create_mysql_engine(profile.mysql, settings)
        except Exception:
            self.dispose()
            raise

    @contextmanager
    def session(self, profile: str) -> Iterator[Session]:
        """为指定环境借用一个请求期间的只读会话

        Args:
            profile: 环境名称，必须存在且启用

        Yields:
            附带 SQL mode 和服务端版本的会话，退出后回滚事务并归还连接

        Raises:
            UnknownProfileError: 环境不存在或未启用
            SQLAlchemyError: 连接获取或初始化失败
            DatabaseConnectionError: 要求 TLS 但实际连接未加密
        """
        engine = self.engines.get(profile)
        if engine is None:
            raise UnknownProfileError(profile)
        with Session(engine) as session:
            connection = session.connection()
            session.info["sql_mode"] = connection.info["sql_mode"]
            session.info["mysql_version"] = engine.dialect.server_version_info
            yield session

    def dispose(self) -> None:
        """释放当前应用持有的全部连接池"""
        for engine in self.engines.values():
            engine.dispose()
