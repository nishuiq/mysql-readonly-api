from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AppConfig:
    """应用基础配置。"""

    name: str
    sql_log: bool


@dataclass(frozen=True)
class ServerConfig:
    """服务启动配置。"""

    host: str
    port: int
    reload: bool


@dataclass(frozen=True)
class MysqlPoolConfig:
    """MySQL 连接池配置。"""

    size: int
    max_overflow: int
    timeout: int
    recycle: int
    pre_ping: bool


@dataclass(frozen=True)
class MysqlConfig:
    """MySQL 连接配置。"""

    host: str
    port: int
    username: str
    password: str
    use_unicode: bool
    character_encoding: str
    zero_datetime_behavior: str
    use_ssl: bool
    server_timezone: str
    pool: MysqlPoolConfig


@dataclass(frozen=True)
class QueryConfig:
    """查询默认配置。"""

    default_limit: int
    max_limit: int
    timeout_ms: int


@dataclass(frozen=True)
class ProfileConfig:
    """一个可访问的 MySQL 数据库配置。"""

    name: str
    description: str
    enabled: bool
    mysql: MysqlConfig


@dataclass(frozen=True)
class Settings:
    """应用配置。"""

    app: AppConfig
    server: ServerConfig
    query: QueryConfig
    profiles: dict[str, ProfileConfig]

    @property
    def enabled_profiles(self) -> dict[str, ProfileConfig]:
        """返回按配置顺序排列的已启用 profile。"""
        return {name: profile for name, profile in self.profiles.items() if profile.enabled}


PROFILE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def load_settings() -> Settings:
    """读取 YAML 并转换成配置对象。"""
    config = load_config_dict()
    app = section(config, "app")
    server = section(config, "server")
    return Settings(
        app=AppConfig(
            name=str(app["name"]),
            sql_log=bool(app["sql_log"]),
        ),
        server=ServerConfig(
            host=str(server["host"]),
            port=int(server["port"]),
            reload=bool(server["reload"]),
        ),
        query=query_config(config),
        profiles=profile_configs(config),
    )


def load_config_dict() -> dict[str, Any]:
    """读取 YAML 配置文件。"""
    config_path = Path("config.yaml")
    if not config_path.exists():
        raise RuntimeError(f"Config file not found: {config_path}")
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def section(config: dict[str, Any], name: str) -> dict[str, Any]:
    """读取指定配置段。"""
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise RuntimeError(f"Config section must be an object: {name}")
    return value


def profile_configs(config: dict[str, Any]) -> dict[str, ProfileConfig]:
    """读取全部 profile，并校验用于 URL 路径的名称。"""
    profiles = section(config, "profiles")
    result: dict[str, ProfileConfig] = {}
    for raw_name, value in profiles.items():
        name = str(raw_name).strip()
        if not PROFILE_NAME_PATTERN.fullmatch(name):
            raise RuntimeError(f"Invalid profile name: {name}. Use lowercase letters, numbers, '-' or '_'.")
        if not isinstance(value, dict):
            raise RuntimeError(f"Profile config must be an object: {name}")
        description = str(value.get("description", "")).strip()
        if not description:
            raise RuntimeError(f"Profile description is required: {name}")
        enabled = value.get("enabled", False)
        if not isinstance(enabled, bool):
            raise RuntimeError(f"Profile enabled must be true or false: {name}")
        result[name] = ProfileConfig(
            name=name,
            description=description,
            enabled=enabled,
            mysql=mysql_config(value),
        )
    return result


def mysql_config(config: dict[str, Any]) -> MysqlConfig:
    """读取 MySQL 配置。"""
    mysql = section(config, "mysql")
    pool = section(mysql, "pool")
    return MysqlConfig(
        host=str(mysql["host"]),
        port=int(mysql["port"]),
        username=str(mysql["username"]),
        password=str(mysql["password"]),
        use_unicode=bool(mysql["use_unicode"]),
        character_encoding=str(mysql["character_encoding"]),
        zero_datetime_behavior=str(mysql["zero_datetime_behavior"]),
        use_ssl=bool(mysql["use_ssl"]),
        server_timezone=str(mysql["server_timezone"]),
        pool=MysqlPoolConfig(
            size=int(pool["size"]),
            max_overflow=int(pool["max_overflow"]),
            timeout=int(pool["timeout"]),
            recycle=int(pool["recycle"]),
            pre_ping=bool(pool["pre_ping"]),
        ),
    )


def query_config(config: dict[str, Any]) -> QueryConfig:
    """读取查询配置。"""
    query = section(config, "query")
    return QueryConfig(
        default_limit=int(query["default_limit"]),
        max_limit=int(query["max_limit"]),
        timeout_ms=int(query["timeout_ms"]),
    )


settings = load_settings()
