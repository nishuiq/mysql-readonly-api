"""提供来自完整示例文件的测试配置，避免读取本地业务配置"""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml

from app.config import MysqlConfig, settings_from_dict


def example_config() -> dict[str, Any]:
    """读取一份独立的完整示例配置

    Returns:
        可由每个用例独立修改的配置映射，不包含本地业务连接信息
    """
    path = Path(__file__).resolve().parents[1] / "config.example.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def example_mysql() -> MysqlConfig:
    """从完整示例中构造 MySQL 配置

    Returns:
        仅用于测试准备的示例环境连接配置，不建立数据库连接
    """
    return settings_from_dict(example_config()).profiles["example-dev"].mysql


def temporary_directory() -> TemporaryDirectory[str]:
    """为单个用例建立项目内的临时目录

    Returns:
        位于项目 temp/test-files 下的目录上下文，退出时只清理该用例的目录
    """
    root = Path(__file__).resolve().parents[1] / "temp" / "test-files"
    root.mkdir(parents=True, exist_ok=True)
    return TemporaryDirectory(prefix="case-", dir=root)
