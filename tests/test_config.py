import os
import unittest
from unittest.mock import patch

from config import ConfigurationError, Settings


BASE_ENV = {
    "TELEGRAM_BOT_TOKEN": "token-de-teste",
    "TELEGRAM_ALLOWED_USER_ID": "123456",
}


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        dotenv_patcher = patch("config.load_dotenv")
        dotenv_patcher.start()
        self.addCleanup(dotenv_patcher.stop)

    def test_loads_minimum_valid_configuration(self) -> None:
        with patch.dict(os.environ, BASE_ENV, clear=True):
            settings = Settings.from_env(validate_codex=False)
        self.assertEqual(settings.telegram_allowed_user_id, 123456)
        self.assertEqual(settings.history_max_exchanges, 10)
        self.assertIsNone(settings.groq_api_key)
        self.assertFalse(settings.queue_routing_enabled)
        self.assertEqual(settings.queue_database_path, "data/inemacabot.sqlite3")
        self.assertIsNone(settings.agnes_api_key)
        self.assertEqual(settings.vsvideo_max_image_bytes, 10 * 1024 * 1024)
        self.assertEqual(settings.codex_image_timeout_seconds, 600)
        self.assertEqual(settings.codex_agnes_timeout_seconds, 7200)

    def test_rejects_missing_token(self) -> None:
        with patch.dict(
            os.environ, {"TELEGRAM_ALLOWED_USER_ID": "123"}, clear=True
        ):
            with self.assertRaises(ConfigurationError):
                Settings.from_env(validate_codex=False)

    def test_rejects_non_numeric_user_id(self) -> None:
        env = {**BASE_ENV, "TELEGRAM_ALLOWED_USER_ID": "não-é-número"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env(validate_codex=False)

    def test_rejects_invalid_history_limit(self) -> None:
        env = {**BASE_ENV, "HISTORY_MAX_EXCHANGES": "0"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env(validate_codex=False)

    def test_parses_queue_configuration(self) -> None:
        env = {
            **BASE_ENV,
            "QUEUE_ROUTING_ENABLED": "true",
            "WORKER_POLL_INTERVAL_MS": "500",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env(validate_codex=False)
        self.assertTrue(settings.queue_routing_enabled)
        self.assertEqual(settings.worker_poll_interval_seconds, 0.5)

    def test_rejects_invalid_boolean(self) -> None:
        env = {**BASE_ENV, "QUEUE_ROUTING_ENABLED": "talvez"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env(validate_codex=False)

    def test_rejects_empty_database_path(self) -> None:
        env = {**BASE_ENV, "QUEUE_DATABASE_PATH": " "}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env(validate_codex=False)


if __name__ == "__main__":
    unittest.main()
