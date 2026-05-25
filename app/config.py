from __future__ import annotations

import argparse
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

    default_offset: int
    default_limit: int
    max_limit: int
    timeout_ms: int


@dataclass(frozen=True)
class Settings:
    """应用配置。"""

    profile: str
    app: AppConfig
    server: ServerConfig
    mysql: MysqlConfig
    query: QueryConfig


def load_settings(profile: str | None = None) -> Settings:
    """读取 YAML 并转换成配置对象。"""
    config = load_config_dict()
    profile_name = resolve_profile_name(config, profile)
    profile_config = selected_profile(config, profile_name)
    app = section(config, "app")
    server = section(profile_config, "server")
    return Settings(
        profile=profile_name,
        app=AppConfig(
            name=str(app["name"]),
            sql_log=bool(app["sql_log"]),
        ),
        server=ServerConfig(
            host=str(server["host"]),
            port=int(server["port"]),
            reload=bool(server["reload"]),
        ),
        mysql=mysql_config(profile_config),
        query=query_config(config),
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


def resolve_profile_name(config: dict[str, Any], profile: str | None = None) -> str:
    """解析当前启用的 profile。"""
    selected = profile or cli_profile() or config.get("active")
    if selected is None or str(selected).strip() == "":
        raise RuntimeError("Active profile is required. Set active or pass --profile.")
    return str(selected).strip()


def cli_profile() -> str | None:
    """从命令行参数读取 profile。"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profile")
    args, _ = parser.parse_known_args()
    return args.profile


def selected_profile(config: dict[str, Any], profile: str) -> dict[str, Any]:
    """读取当前启用的 profile 配置。"""
    profiles = section(config, "profiles")
    value = profiles.get(profile)
    if not isinstance(value, dict):
        available = ", ".join(sorted(str(name) for name in profiles))
        suffix = f" Available profiles: {available}." if available else ""
        raise RuntimeError(f"Unknown profile: {profile}.{suffix}")
    return value


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
        default_offset=int(query["default_offset"]),
        default_limit=int(query["default_limit"]),
        max_limit=int(query["max_limit"]),
        timeout_ms=int(query["timeout_ms"]),
    )


settings = load_settings()
