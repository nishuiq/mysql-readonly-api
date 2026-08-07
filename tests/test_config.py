import importlib.util
import os
import sys
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"

CONFIG_YAML = """
app:
  name: mysql-readonly-api
  sql_log: true

server:
  host: 127.0.0.1
  port: 8765
  reload: false

query:
  default_limit: 500
  max_limit: 5000
  timeout_ms: 15000

profiles:
  example-dev:
    enabled: true
    description: Example development database
    mysql:
      host: 127.0.0.1
      port: 3306
      username: readonly
      password: password
      use_unicode: true
      character_encoding: utf8
      zero_datetime_behavior: convert_to_null
      use_ssl: true
      server_timezone: "+08:00"
      pool:
        size: 5
        max_overflow: 10
        timeout: 30
        recycle: 3600
        pre_ping: true

  example-prod:
    enabled: false
    description: Example production read-only database
    mysql:
      host: 10.0.0.1
      port: 13307
      username: readonly
      password: password
      use_unicode: true
      character_encoding: utf8
      zero_datetime_behavior: convert_to_null
      use_ssl: true
      server_timezone: "+08:00"
      pool:
        size: 3
        max_overflow: 4
        timeout: 5
        recycle: 600
        pre_ping: true
"""


class ConfigTest(unittest.TestCase):
    def load_settings(self, config_yaml: str):
        old_cwd = Path.cwd()
        module_name = f"config_under_test_{uuid.uuid4().hex}"

        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "config.yaml").write_text(textwrap.dedent(config_yaml), encoding="utf-8")
            os.chdir(temp_dir)

            spec = importlib.util.spec_from_file_location(module_name, CONFIG_PATH)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Cannot load config module: {CONFIG_PATH}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
                return module.settings
            finally:
                sys.modules.pop(module_name, None)
                os.chdir(old_cwd)

    def test_loads_global_server_and_all_profiles(self) -> None:
        settings = self.load_settings(CONFIG_YAML)

        self.assertEqual(settings.server.port, 8765)
        self.assertEqual(list(settings.profiles), ["example-dev", "example-prod"])
        self.assertEqual(settings.profiles["example-dev"].description, "Example development database")
        self.assertEqual(settings.profiles["example-prod"].mysql.host, "10.0.0.1")
        self.assertEqual(settings.profiles["example-prod"].mysql.pool.size, 3)

    def test_exposes_only_enabled_profiles(self) -> None:
        settings = self.load_settings(CONFIG_YAML)

        self.assertEqual(list(settings.enabled_profiles), ["example-dev"])

    def test_query_offset_is_not_configurable(self) -> None:
        settings = self.load_settings(CONFIG_YAML)

        self.assertFalse(hasattr(settings.query, "default_offset"))

    def test_rejects_invalid_profile_name(self) -> None:
        invalid_config = CONFIG_YAML.replace("  example-dev:\n", "  Example Dev:\n", 1)

        with self.assertRaisesRegex(RuntimeError, "Invalid profile name: Example Dev"):
            self.load_settings(invalid_config)

    def test_requires_profile_description(self) -> None:
        missing_description = CONFIG_YAML.replace("    description: Example development database\n", "", 1)

        with self.assertRaisesRegex(RuntimeError, "Profile description is required: example-dev"):
            self.load_settings(missing_description)

    def test_requires_boolean_enabled(self) -> None:
        invalid_enabled = CONFIG_YAML.replace("    enabled: true\n", "    enabled: yes please\n", 1)

        with self.assertRaisesRegex(RuntimeError, "Profile enabled must be true or false: example-dev"):
            self.load_settings(invalid_enabled)


if __name__ == "__main__":
    unittest.main()
