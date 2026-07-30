"""Processo watcher que entrega jobs finais."""

from __future__ import annotations

import asyncio
import logging
import signal

from telegram import Bot

from config import Settings
from delivery.service import DeliveryService
from queueing.job_repository import JobRepository


LOGGER = logging.getLogger(__name__)


async def async_main() -> None:
    settings = Settings.from_env()
    repository = JobRepository(settings.queue_database_path)
    repository.migrate()
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stopping.set)
    async with Bot(settings.telegram_bot_token) as bot:
        service = DeliveryService(
            bot=bot,
            repository=repository,
            work_root=settings.job_work_root,
        )
        while not stopping.is_set():
            job = repository.claim_delivery(
                max_attempts=settings.delivery_max_attempts
            )
            if job is None:
                try:
                    await asyncio.wait_for(
                        stopping.wait(),
                        timeout=settings.delivery_poll_interval_seconds,
                    )
                except TimeoutError:
                    pass
                continue
            try:
                await service.deliver(job)
            except Exception:
                LOGGER.exception(
                    "Falha ao entregar resultado.", extra={"job_id": job.id}
                )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
