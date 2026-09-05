from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AppConfig:
    name: str = "mysql-readonly-api"
    sql_log: bool = False


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    reload: bool = False


@dataclass(frozen=True)
class MysqlPoolConfig:
    size: int = 5
    max_overflow: int = 10
    timeout: int = 30
    recycle: int = 3600
    pre_ping: bool = True


@dataclass(frozen=True)
class MysqlConfig:
    host: str
    username: str
    password: str = field(repr=False)
    port: int = 3306
    use_unicode: bool = True
    character_encoding: str = "utf8mb4"
    use_ssl: bool = True
    ssl_ca: str | None = None
    server_timezone: str = "+08:00"
    connect_timeout: int = 10
    read_timeout: int = 30
    write_timeout: int = 30
    pool: MysqlPoolConfig = field(default_factory=MysqlPoolConfig)


@dataclass(frozen=True)
class QueryConfig:
    default_limit: int = 500
    max_limit: int = 5000
    timeout_ms: int = 15000


@dataclass(frozen=True)
class ProfileConfig:
    name: str
    description: str
    enabled: bool
    mysql: MysqlConfig


@dataclass(frozen=True)
class Settings:
    app: AppConfig
    server: ServerConfig
    query: QueryConfig
    profiles: dict[str, ProfileConfig]

    @property
    def enabled_profiles(self) -> dict[str, ProfileConfig]:
        return {name: profile for name, profile in self.profiles.items() if profile.enabled}


PROFILE_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*")


def load_settings(path: str | Path = "config.yaml") -> Settings:
    """仅在应用创建时读取配置，导入模块不会访问本地配置或数据库。"""
    config_path = Path(path)
    if not config_path.is_file():
        raise RuntimeError(f"Config file not found: {config_path}")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        # YAML parser errors can contain credentials from the source line.
        raise RuntimeError(f"Invalid YAML configuration: {config_path}") from None
    return settings_from_dict(config if config is not None else {})


def settings_from_dict(config: dict[str, Any]) -> Settings:
    if not isinstance(config, dict):
        raise RuntimeError("Config must be an object.")
    app = section(config, "app")
    server = section(config, "server")
    return Settings(
        app=AppConfig(
            name=string_value(app, "name", "mysql-readonly-api"),
            sql_log=bool_value(app, "sql_log", False),
        ),
        server=ServerConfig(
            host=string_value(server, "host", "127.0.0.1"),
            port=int_value(server, "port", 8765, maximum=65535),
            reload=bool_value(server, "reload", False),
        ),
        query=query_config(config),
        profiles=profile_configs(config),
    )


def section(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise RuntimeError(f"Config section must be an object: {name}")
    return value


def bool_value(config: dict[str, Any], name: str, default: bool) -> bool:
    value = config.get(name, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"Config {name} must be true or false.")
    return value


def int_value(config: dict[str, Any], name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    value = config.get(name, default)
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        bounds = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise RuntimeError(f"Config {name} must be an integer {bounds}.")
    return value


def string_value(config: dict[str, Any], name: str, default: str | None = None, *, empty: bool = False) -> str:
    value = config.get(name, default)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise RuntimeError(f"Config {name} must be {'a' if empty else 'a non-empty'} string.")
    return value


def profile_configs(config: dict[str, Any]) -> dict[str, ProfileConfig]:
    result: dict[str, ProfileConfig] = {}
    for name, value in section(config, "profiles").items():
        if not isinstance(name, str) or not PROFILE_NAME_PATTERN.fullmatch(name):
            raise RuntimeError("Invalid profile name. Use lowercase letters, numbers, '-' or '_'.")
        if not isinstance(value, dict):
            raise RuntimeError(f"Profile config must be an object: {name}")
        result[name] = ProfileConfig(
            name=name,
            description=string_value(value, "description").strip(),
            enabled=bool_value(value, "enabled", False),
            mysql=mysql_config(value),
        )
    return result


def mysql_config(config: dict[str, Any]) -> MysqlConfig:
    mysql = section(config, "mysql")
    pool = section(mysql, "pool")
    if "zero_datetime_behavior" in mysql:
        raise RuntimeError("Config zero_datetime_behavior was removed; delete it to preserve returned values.")
    ssl_ca = mysql.get("ssl_ca")
    if ssl_ca is not None and (not isinstance(ssl_ca, str) or not ssl_ca.strip()):
        raise RuntimeError("Config ssl_ca must be a certificate path or null.")
    use_ssl = bool_value(mysql, "use_ssl", True)
    if ssl_ca and not use_ssl:
        raise RuntimeError("Config ssl_ca requires use_ssl: true.")
    return MysqlConfig(
        host=string_value(mysql, "host"),
        port=int_value(mysql, "port", 3306, maximum=65535),
        username=string_value(mysql, "username"),
        password=string_value(mysql, "password", empty=True),
        use_unicode=bool_value(mysql, "use_unicode", True),
        character_encoding=string_value(mysql, "character_encoding", "utf8mb4"),
        use_ssl=use_ssl,
        ssl_ca=ssl_ca,
        server_timezone=string_value(mysql, "server_timezone", "+08:00", empty=True),
        connect_timeout=int_value(mysql, "connect_timeout", 10),
        read_timeout=int_value(mysql, "read_timeout", 30),
        write_timeout=int_value(mysql, "write_timeout", 30),
        pool=MysqlPoolConfig(
            size=int_value(pool, "size", 5),
            max_overflow=int_value(pool, "max_overflow", 10, minimum=0),
            timeout=int_value(pool, "timeout", 30),
            recycle=int_value(pool, "recycle", 3600),
            pre_ping=bool_value(pool, "pre_ping", True),
        ),
    )


def query_config(config: dict[str, Any]) -> QueryConfig:
    query = section(config, "query")
    result = QueryConfig(
        default_limit=int_value(query, "default_limit", 500),
        max_limit=int_value(query, "max_limit", 5000),
        timeout_ms=int_value(query, "timeout_ms", 15000),
    )
    if result.default_limit > result.max_limit:
        raise RuntimeError("Config default_limit must not exceed max_limit.")
    return result
