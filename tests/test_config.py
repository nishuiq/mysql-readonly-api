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
active: dev

app:
  name: mysql-readonly-api
  sql_log: true

query:
  default_offset: 0
  default_limit: 500
  max_limit: 5000
  timeout_ms: 15000

profiles:
  dev:
    server:
      host: 127.0.0.1
      port: 8765
      reload: false
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

  prod:
    server:
      host: 127.0.0.1
      port: 8766
      reload: false
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
    def load_settings(self, config_yaml: str, cli_profile: str | None = None):
        old_cwd = Path.cwd()
        old_argv = sys.argv[:]
        module_name = f"config_under_test_{uuid.uuid4().hex}"

        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "config.yaml").write_text(textwrap.dedent(config_yaml), encoding="utf-8")
            os.chdir(temp_dir)
            sys.argv = ["main.py"]
            if cli_profile:
                sys.argv.extend(["--profile", cli_profile])

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
                sys.argv = old_argv
                os.chdir(old_cwd)

    def test_uses_active_profile_by_default(self) -> None:
        settings = self.load_settings(CONFIG_YAML)

        self.assertEqual(settings.profile, "dev")
        self.assertEqual(settings.server.port, 8765)
        self.assertEqual(settings.mysql.username, "readonly")

    def test_cli_profile_overrides_active(self) -> None:
        settings = self.load_settings(CONFIG_YAML, cli_profile="prod")

        self.assertEqual(settings.profile, "prod")
        self.assertEqual(settings.server.port, 8766)
        self.assertEqual(settings.mysql.host, "10.0.0.1")
        self.assertEqual(settings.mysql.pool.size, 3)

    def test_rejects_unknown_profile(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Unknown profile: missing"):
            self.load_settings(CONFIG_YAML, cli_profile="missing")


if __name__ == "__main__":
    unittest.main()
