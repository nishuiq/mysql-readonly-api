import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.config import load_settings, settings_from_dict


def config_dict():
    return {
        "profiles": {
            "dev": {
                "description": "Development",
                "enabled": True,
                "mysql": {"host": "127.0.0.1", "username": "reader", "password": "secret", "use_ssl": False},
            },
            "prod": {
                "description": "Production",
                "enabled": False,
                "mysql": {"host": "db.example", "username": "reader", "password": "secret"},
            },
        }
    }


class ConfigTest(unittest.TestCase):
    def test_defaults_and_enabled_profiles(self):
        settings = settings_from_dict(config_dict())
        self.assertEqual(list(settings.enabled_profiles), ["dev"])
        self.assertEqual(settings.server.port, 8765)
        self.assertEqual(settings.profiles["dev"].mysql.character_encoding, "utf8mb4")
        self.assertNotIn("secret", repr(settings))

    def test_invalid_types_ranges_and_relations(self):
        for config in [
            {"server": {"reload": "false"}},
            {"query": {"default_limit": 0}},
            {"query": {"max_limit": 10}},
            {"query": {"timeout_ms": True}},
            {"server": {"port": 65536}},
            {"app": []},
            {"profiles": {"Invalid Name": {}}},
        ]:
            with self.subTest(config=config), self.assertRaises(RuntimeError):
                settings_from_dict(config)
        for field, value in [
            ("use_ssl", "false"),
            ("connect_timeout", 0),
            ("zero_datetime_behavior", "convert_to_null"),
        ]:
            config = config_dict()
            config["profiles"]["dev"]["mysql"][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                settings_from_dict(config)

    def test_yaml_error_does_not_include_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.yaml"
            path.write_text("password: [supersecret\n", encoding="utf-8")
            with self.assertRaises(RuntimeError) as error:
                load_settings(path)
            self.assertNotIn("supersecret", str(error.exception))

    def test_import_does_not_require_config(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            code = f"import sys; sys.path.insert(0, {str(root)!r}); import app.factory, app.text_format, main"
            result = subprocess.run([sys.executable, "-c", code], cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_example_config_is_valid_and_profiles_disabled(self):
        settings = load_settings(Path(__file__).resolve().parents[1] / "config.example.yaml")
        self.assertEqual(settings.enabled_profiles, {})
