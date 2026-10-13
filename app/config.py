"""读取完整的显式配置并在应用启动前校验字段、类型和约束"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AppConfig:
    """表示应用标识与 SQL 日志设置

    Attributes:
        name: API 文档和应用使用的名称
        sql_log: 是否记录 SQL 及绑定参数，不记录结果集
    """

    name: str
    sql_log: bool


@dataclass(frozen=True)
class ServerConfig:
    """表示单个 REST 服务的监听与重载设置

    Attributes:
        host: REST 监听地址
        port: REST 监听端口，范围为 1 至 65535
        reload: 是否启用开发环境的自动重载
    """

    host: str
    port: int
    reload: bool


@dataclass(frozen=True)
class MysqlPoolConfig:
    """表示一个 profile 独占的连接池设置

    Attributes:
        size: 常驻连接数量上限，必须为正数
        max_overflow: 常驻连接之外允许临时增加的连接数，可以为零
        timeout: 等待可用连接的最长时间，单位为秒
        recycle: 连接使用年限达到此秒数后，在再次取用时回收
        pre_ping: 是否在取用连接时检查连接存活状态
    """

    size: int
    max_overflow: int
    timeout: int
    recycle: int
    pre_ping: bool


@dataclass(frozen=True)
class MysqlConfig:
    """表示一个 MySQL 数据源的完整连接配置

    Attributes:
        host: MySQL 主机地址，启用 TLS 时也用于证书主机名校验
        port: MySQL 端口，范围为 1 至 65535
        username: 数据库账号
        password: 数据库密码，可为空，不出现在对象的调试表示中
        use_unicode: 是否将字符字段解码为字符串，关闭后按二进制展示驱动返回的 bytes
        character_encoding: 连接字符集
        use_ssl: 是否要求 TLS 加密并校验证书
        ssl_ca: CA 文件路径，显式为 None 时使用系统信任库
        server_timezone: MySQL 会话时区，空字符串表示保留服务端设置
        connect_timeout: 建立连接的超时时间，单位为秒
        io_timeout: socket 接收结果与发送请求的超时时间，单位为秒
        pool: 当前数据源的连接池配置
    """

    host: str
    port: int
    username: str
    password: str = field(repr=False)
    use_unicode: bool
    character_encoding: str
    use_ssl: bool
    ssl_ca: str | None
    server_timezone: str
    connect_timeout: int
    io_timeout: int
    pool: MysqlPoolConfig


@dataclass(frozen=True)
class QueryConfig:
    """表示查询结果规模与执行时间限制

    Attributes:
        limit: 请求未传 limit 时的返回行数，也是请求不能突破的硬上限
        timeout_ms: MySQL max_execution_time 的毫秒值，不覆盖所有 SHOW 或存储程序
    """

    limit: int
    timeout_ms: int


@dataclass(frozen=True)
class ProfileConfig:
    """表示一个可由 URL 选择的数据库环境

    Attributes:
        name: 配置映射中的环境名称，用于 URL，不在 profile 配置体中重复填写
        description: 向调用方展示的环境用途
        enabled: 是否暴露该环境并创建对应连接池
        mysql: 该环境的完整 MySQL 配置，禁用环境也须显式配置
    """

    name: str
    description: str
    enabled: bool
    mysql: MysqlConfig


@dataclass(frozen=True)
class Settings:
    """表示应用启动时读取的完整配置快照

    Attributes:
        app: 应用名称与日志设置
        server: REST 监听设置
        query: 查询行数与执行时间限制
        profiles: 校验后不可增删或替换的环境配置，包含禁用环境，可显式为空映射
    """

    app: AppConfig
    server: ServerConfig
    query: QueryConfig
    profiles: frozendict[str, ProfileConfig]

    @property
    def enabled_profiles(self) -> frozendict[str, ProfileConfig]:
        """筛选允许通过 API 访问的环境

        Returns:
            保持配置顺序的不可变启用环境映射，没有启用环境时为空
        """
        return frozendict((name, profile) for name, profile in self.profiles.items() if profile.enabled)


PROFILE_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*")


def load_settings(path: str | Path = "config.yaml") -> Settings:
    """从指定 YAML 文件读取完整配置

    Args:
        path: 配置文件路径，省略时使用工作目录下的 config.yaml

    Returns:
        已通过字段、类型和范围校验的配置，不为缺项补值

    Raises:
        RuntimeError: 文件无法读取、YAML 无效或配置不符合当前字段约束
    """
    config_path = Path(path)
    try:
        source = config_path.read_text(encoding="utf-8")
    except OSError, UnicodeError:
        raise RuntimeError(f"Cannot read UTF-8 config file: {config_path}") from None
    try:
        config = yaml.safe_load(source)
    except yaml.YAMLError:
        # YAML 解析异常可能包含密码所在的原始行
        raise RuntimeError(f"Invalid YAML configuration: {config_path}") from None
    return settings_from_dict(config)


def field_names(model: type) -> set[str]:
    """读取配置 dataclass 声明的字段名称

    Args:
        model: 配置 dataclass，用其字段定义确定当前允许的配置键

    Returns:
        字段名称集合，不包含任何缺省值
    """
    return {item.name for item in fields(model)}


def object_value(value: Any, path: str, expected: Collection[str] | None = None) -> dict[str, Any]:
    """校验配置对象及其完整字段集合

    Args:
        value: YAML 中读取的配置节点
        path: 节点的完整路径，根节点使用空字符串
        expected: 必须且仅允许出现的键，为 None 时接受动态名称映射

    Returns:
        原始配置映射，不插入、删除或转换字段

    Raises:
        RuntimeError: 节点不是映射、键不是字符串，或存在未知字段或缺项
    """
    if not isinstance(value, dict):
        raise RuntimeError(f"Config {path or '<root>'} must be an object.")
    if any(not isinstance(key, str) for key in value):
        raise RuntimeError(f"Config {path or '<root>'} keys must be strings.")
    if expected is not None:
        prefix = f"{path}." if path else ""
        unknown = set(value) - set(expected)
        if unknown:
            raise RuntimeError("Unknown config: " + ", ".join(prefix + name for name in sorted(unknown)))
        missing = set(expected) - set(value)
        if missing:
            raise RuntimeError("Missing config: " + ", ".join(prefix + name for name in sorted(missing)))
    return value


def settings_from_dict(config: Any) -> Settings:
    """将完整配置映射转换为应用配置对象

    Args:
        config: YAML 解析结果，必须包含全部根节点和各节点声明的字段

    Returns:
        不包含隐式缺省值的配置对象

    Raises:
        RuntimeError: 任意配置字段缺失、未知、类型错误或违反约束
    """
    root = object_value(config, "", field_names(Settings))
    app = object_value(root["app"], "app", field_names(AppConfig))
    server = object_value(root["server"], "server", field_names(ServerConfig))
    query = object_value(root["query"], "query", field_names(QueryConfig))
    return Settings(
        app=AppConfig(
            name=string_value(app["name"], "app.name"),
            sql_log=bool_value(app["sql_log"], "app.sql_log"),
        ),
        server=ServerConfig(
            host=string_value(server["host"], "server.host"),
            port=int_value(server["port"], "server.port", maximum=65535),
            reload=bool_value(server["reload"], "server.reload"),
        ),
        query=QueryConfig(
            limit=int_value(query["limit"], "query.limit"),
            timeout_ms=int_value(query["timeout_ms"], "query.timeout_ms"),
        ),
        profiles=profile_configs(root["profiles"]),
    )


def bool_value(value: Any, path: str) -> bool:
    """读取显式布尔值并拒绝字符串或数字替代

    Args:
        value: 配置中的原始值
        path: 用于错误提示的完整字段路径

    Returns:
        未经隐式转换的布尔值

    Raises:
        RuntimeError: 值不是布尔值
    """
    if not isinstance(value, bool):
        raise RuntimeError(f"Config {path} must be true or false.")
    return value


def int_value(value: Any, path: str, minimum: int = 1, maximum: int | None = None) -> int:
    """读取约束范围内的显式整数

    Args:
        value: 配置中的原始值，布尔值不视为整数
        path: 用于错误提示的完整字段路径
        minimum: 允许的最小值，包含边界
        maximum: 允许的最大值，包含边界，为 None 时不设最大值

    Returns:
        满足范围约束且未经隐式转换的整数

    Raises:
        RuntimeError: 值不是整数或超出允许范围
    """
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        bounds = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise RuntimeError(f"Config {path} must be an integer {bounds}.")
    return value


def string_value(value: Any, path: str, *, empty: bool = False) -> str:
    """读取显式字符串并按字段约束检查空值

    Args:
        value: 配置中的原始值
        path: 用于错误提示的完整字段路径
        empty: 是否允许空字符串或仅含空白的字符串

    Returns:
        原始字符串，不裁剪其中的空白或转义内容

    Raises:
        RuntimeError: 值不是字符串，或字段不允许为空
    """
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise RuntimeError(f"Config {path} must be {'a' if empty else 'a non-empty'} string.")
    return value


def profile_configs(config: Any) -> frozendict[str, ProfileConfig]:
    """解析以环境名称为键的完整 profile 配置

    Args:
        config: profiles 节点，允许显式为空映射

    Returns:
        与输入字典隔离且保持配置顺序的不可变环境映射，包括禁用环境

    Raises:
        RuntimeError: 环境名称不合法，或任意环境的配置缺失、未知或无效
    """
    profiles = object_value(config, "profiles")
    result: dict[str, ProfileConfig] = {}
    for name, value in profiles.items():
        path = f"profiles.{name}"
        if not PROFILE_NAME_PATTERN.fullmatch(name):
            raise RuntimeError(f"Invalid config {path}: use lowercase letters, numbers, '-' or '_'.")
        profile = object_value(value, path, field_names(ProfileConfig) - {"name"})
        result[name] = ProfileConfig(
            name=name,
            description=string_value(profile["description"], f"{path}.description"),
            enabled=bool_value(profile["enabled"], f"{path}.enabled"),
            mysql=mysql_config(profile["mysql"], f"{path}.mysql"),
        )
    return frozendict(result)


def mysql_config(config: Any, path: str) -> MysqlConfig:
    """解析一个 profile 的完整 MySQL 与连接池配置

    Args:
        config: 当前环境的 mysql 配置节点
        path: 当前节点的完整路径，用于定位字段错误

    Returns:
        保留显式输入值的 MySQL 配置，ssl_ca 必须填写路径或 None

    Raises:
        RuntimeError: 配置字段缺失、未知、值无效，或关闭 TLS 时仍指定 CA 文件
    """
    mysql = object_value(config, path, field_names(MysqlConfig))
    pool_path = f"{path}.pool"
    pool = object_value(mysql["pool"], pool_path, field_names(MysqlPoolConfig))
    ssl_ca = mysql["ssl_ca"]
    if ssl_ca is not None:
        ssl_ca = string_value(ssl_ca, f"{path}.ssl_ca")
    use_ssl = bool_value(mysql["use_ssl"], f"{path}.use_ssl")
    if ssl_ca is not None and not use_ssl:
        raise RuntimeError(f"Config {path}.ssl_ca requires {path}.use_ssl: true.")
    return MysqlConfig(
        host=string_value(mysql["host"], f"{path}.host"),
        port=int_value(mysql["port"], f"{path}.port", maximum=65535),
        username=string_value(mysql["username"], f"{path}.username"),
        password=string_value(mysql["password"], f"{path}.password", empty=True),
        use_unicode=bool_value(mysql["use_unicode"], f"{path}.use_unicode"),
        character_encoding=string_value(mysql["character_encoding"], f"{path}.character_encoding"),
        use_ssl=use_ssl,
        ssl_ca=ssl_ca,
        server_timezone=string_value(mysql["server_timezone"], f"{path}.server_timezone", empty=True),
        connect_timeout=int_value(mysql["connect_timeout"], f"{path}.connect_timeout"),
        io_timeout=int_value(mysql["io_timeout"], f"{path}.io_timeout"),
        pool=MysqlPoolConfig(
            size=int_value(pool["size"], f"{pool_path}.size"),
            max_overflow=int_value(pool["max_overflow"], f"{pool_path}.max_overflow", minimum=0),
            timeout=int_value(pool["timeout"], f"{pool_path}.timeout"),
            recycle=int_value(pool["recycle"], f"{pool_path}.recycle"),
            pre_ping=bool_value(pool["pre_ping"], f"{pool_path}.pre_ping"),
        ),
    )
