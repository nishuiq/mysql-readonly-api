"""暴露只读 API 的应用工厂，导入时不加载本地配置"""

from app.factory import create_app

__all__ = ["create_app"]
