"""检查完整显式配置的字段约束、输入类型和加载边界"""

import copy
import subprocess
import sys
import unittest
from pathlib import Path

from app.config import QueryConfig, load_settings, settings_from_dict
from tests.helpers import example_config, temporary_directory


class ConfigTest(unittest.TestCase):
    """覆盖配置读取和完整字段契约"""

    def test_explicit_values_and_enabled_profiles(self):
        """显式配置值完整保留且仅暴露启用环境"""
        config = example_config()
        config["profiles"]["example-dev"]["enabled"] = True
        config["profiles"]["example-dev"]["mysql"]["password"] = "private-password"
        config["profiles"]["disabled"] = copy.deepcopy(config["profiles"]["example-dev"])
        config["profiles"]["disabled"]["enabled"] = False
        config["query"]["limit"] = 37
        config["server"]["port"] = 8888
        settings = settings_from_dict(config)
        self.assertEqual(list(settings.enabled_profiles), ["example-dev"])
        self.assertEqual(settings.query.limit, 37)
        self.assertEqual(settings.server.port, 8888)
        self.assertNotIn("private-password", repr(settings))

    def test_profile_snapshots_reject_in_place_changes(self):
        """完整配置与启用环境快照均拒绝增删和替换 profile"""
        config = example_config()
        config["profiles"]["example-dev"]["enabled"] = True
        settings = settings_from_dict(config)
        original = settings.profiles["example-dev"]
        for name, profiles in [("all", settings.profiles), ("enabled", settings.enabled_profiles)]:
            with self.subTest(snapshot=name):
                with self.assertRaises(TypeError):
                    profiles["extra"] = original
                with self.assertRaises(TypeError):
                    profiles["example-dev"] = original
                with self.assertRaises(TypeError):
                    del profiles["example-dev"]
                self.assertEqual(list(profiles), ["example-dev"])
                self.assertIs(profiles["example-dev"], original)

    def test_profile_snapshot_is_independent_of_input(self):
        """配置快照保留输入顺序且不受输入字典后续修改影响"""
        config = example_config()
        config["profiles"]["example-dev"]["enabled"] = True
        config["profiles"]["another"] = copy.deepcopy(config["profiles"]["example-dev"])
        settings = settings_from_dict(config)
        config["profiles"]["example-dev"]["enabled"] = False
        config["profiles"].clear()
        self.assertEqual(list(settings.profiles), ["example-dev", "another"])
        self.assertEqual(list(settings.enabled_profiles), ["example-dev", "another"])

    def test_every_declared_config_field_is_required(self):
        """任意层级缺少必填字段都会指出完整路径"""
        paths = [
            (),
            ("app",),
            ("server",),
            ("query",),
            ("profiles", "example-dev"),
            ("profiles", "example-dev", "mysql"),
            ("profiles", "example-dev", "mysql", "pool"),
        ]
        for path in paths:
            section = example_config()
            for key in path:
                section = section[key]
            for field in section:
                config = example_config()
                node = config
                for key in path:
                    node = node[key]
                del node[field]
                full_path = ".".join((*path, field))
                with self.subTest(path=full_path), self.assertRaises(RuntimeError) as error:
                    settings_from_dict(config)
                self.assertIn("Missing config: " + full_path, str(error.exception))

    def test_unknown_config_fields_are_rejected_uniformly(self):
        """未知配置字段通过统一字段校验报告"""
        for path in [(), ("query",), ("profiles", "example-dev"), ("profiles", "example-dev", "mysql")]:
            config = example_config()
            node = config
            for key in path:
                node = node[key]
            node["unexpected"] = 1
            with self.subTest(path=path), self.assertRaises(RuntimeError) as error:
                settings_from_dict(config)
            self.assertIn("Unknown config: " + ".".join((*path, "unexpected")), str(error.exception))

    def test_invalid_types_and_ranges_include_field_paths(self):
        """无效类型和越界数值按具体字段报错"""
        values = [
            (("server", "reload"), "false"),
            (("server", "port"), 65536),
            (("query", "limit"), 0),
            (("query", "limit"), None),
            (("query", "timeout_ms"), True),
            (("profiles", "example-dev", "enabled"), 0),
            (("profiles", "example-dev", "mysql", "use_ssl"), "false"),
            (("profiles", "example-dev", "mysql", "connect_timeout"), 0),
            (("profiles", "example-dev", "mysql", "io_timeout"), 0),
            (("profiles", "example-dev", "mysql", "io_timeout"), "30"),
            (("profiles", "example-dev", "mysql", "password"), 123),
        ]
        for path, value in values:
            config = example_config()
            node = config
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(RuntimeError) as error:
                settings_from_dict(config)
            self.assertIn(".".join(path), str(error.exception))

    def test_optional_values_must_be_explicit(self):
        """显式空值表达连接策略而非触发配置补值"""
        config = example_config()
        mysql = config["profiles"]["example-dev"]["mysql"]
        mysql["ssl_ca"] = None
        mysql["password"] = ""
        mysql["server_timezone"] = ""
        parsed = settings_from_dict(config).profiles["example-dev"].mysql
        self.assertIsNone(parsed.ssl_ca)
        self.assertEqual(parsed.password, "")
        self.assertEqual(parsed.server_timezone, "")
        mysql["ssl_ca"] = "test-ca.pem"
        mysql["use_ssl"] = False
        with self.assertRaisesRegex(RuntimeError, "profiles.example-dev.mysql.ssl_ca requires"):
            settings_from_dict(config)

    def test_invalid_sections_and_profile_names_are_rejected(self):
        """配置节点和环境名称必须符合声明结构"""
        for value in [None, [], "config", {}]:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                settings_from_dict(value)
        config = example_config()
        config["profiles"] = {"Invalid Name": config["profiles"]["example-dev"]}
        with self.assertRaisesRegex(RuntimeError, "profiles.Invalid Name"):
            settings_from_dict(config)

    def test_query_config_constructor_requires_explicit_values(self):
        """查询配置构造不提供隐式数值"""
        with self.assertRaises(TypeError):
            QueryConfig()

    def test_empty_profiles_must_be_explicit(self):
        """显式空 profiles 允许启动无数据源应用"""
        config = example_config()
        config["profiles"] = {}
        self.assertEqual(settings_from_dict(config).enabled_profiles, {})

    def test_yaml_error_does_not_include_credentials(self):
        """无效 YAML 的错误消息不回显凭据"""
        with temporary_directory() as directory:
            path = Path(directory) / "bad.yaml"
            path.write_text("password: [supersecret\n", encoding="utf-8")
            with self.assertRaises(RuntimeError) as error:
                load_settings(path)
            self.assertNotIn("supersecret", str(error.exception))

    def test_import_does_not_require_config(self):
        """模块导入不会读取配置文件或建立数据库连接"""
        root = Path(__file__).resolve().parents[1]
        with temporary_directory() as directory:
            code = f"import sys; sys.path.insert(0, {str(root)!r}); import app.factory, app.text_format, main"
            result = subprocess.run([sys.executable, "-c", code], cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_example_config_is_valid_and_profiles_disabled(self):
        """完整示例配置可加载且不会启用示例数据库"""
        settings = load_settings(Path(__file__).resolve().parents[1] / "config.example.yaml")
        self.assertEqual(settings.enabled_profiles, {})
