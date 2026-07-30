import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import _parse_vsvideo_options, test_queue_command, virtual_staging_message


class ForbiddenJobs:
    def __getattr__(self, name):
        raise AssertionError(f"Usuário não autorizado acessou jobs: {name}")


class BotAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unauthorized_user_does_not_access_queue(self) -> None:
        services = SimpleNamespace(
            settings=SimpleNamespace(telegram_allowed_user_id=123),
            jobs=ForbiddenJobs(),
        )
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"services": services}),
            args=["não", "pode"],
        )
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=999),
            effective_message=message,
        )

        await test_queue_command(update, context)

        message.reply_text.assert_not_awaited()

    async def test_unauthorized_user_does_not_download_virtual_staging_photo(
        self,
    ) -> None:
        services = SimpleNamespace(
            settings=SimpleNamespace(telegram_allowed_user_id=123),
            jobs=ForbiddenJobs(),
        )
        bot = SimpleNamespace(get_file=AsyncMock())
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"services": services}),
            bot=bot,
        )
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=999),
            effective_message=message,
        )

        await virtual_staging_message(update, context)

        bot.get_file.assert_not_awaited()
        message.reply_text.assert_not_awaited()


class VirtualStagingOptionsTests(unittest.TestCase):
    def test_defaults_to_six_seconds(self) -> None:
        self.assertEqual(
            _parse_vsvideo_options("/vsvideo"),
            (6, False, "agnes"),
        )

    def test_accepts_automatic_eighteen_seconds(self) -> None:
        self.assertEqual(
            _parse_vsvideo_options("/vsvideo 18"),
            (18, False, "agnes"),
        )

    def test_accepts_eighteen_seconds_with_approval(self) -> None:
        self.assertEqual(
            _parse_vsvideo_options("/vsvideo 18 aprovacao"),
            (18, True, "agnes"),
        )

    def test_accepts_codex_images_with_optional_approval(self) -> None:
        self.assertEqual(
            _parse_vsvideo_options("/vsvideo 18 codex aprovacao"),
            (18, True, "codex"),
        )
        self.assertEqual(
            _parse_vsvideo_options("/vsvideo 18 openai"),
            (18, False, "codex"),
        )

    def test_rejects_approval_for_short_video(self) -> None:
        with self.assertRaises(ValueError):
            _parse_vsvideo_options("/vsvideo 6 aprovacao")

    def test_rejects_codex_images_for_short_video(self) -> None:
        with self.assertRaises(ValueError):
            _parse_vsvideo_options("/vsvideo 6 codex")


if __name__ == "__main__":
    unittest.main()
