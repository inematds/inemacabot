"""Ponto de entrada dos três workers."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from agents.factory import AgentFactory
from config import Settings
from queueing.job_repository import JobRepository
from queueing.models import QueueName
from skills.registry import SkillRegistry
from workers.worker import QueueWorker


async def async_main(queue: QueueName) -> None:
    settings = Settings.from_env()
    repository = JobRepository(settings.queue_database_path)
    repository.migrate()
    registry = SkillRegistry.from_file(settings.skills_registry_path)
    factory = AgentFactory(
        codex_binary=settings.codex_binary,
        codex_model=settings.codex_model,
        timeout_seconds=settings.job_execution_timeout_seconds,
        test_delay_seconds=settings.test_skill_delay_seconds,
        vsv_skills_root=settings.vsv_skills_root,
    )
    worker = QueueWorker(
        queue=queue,
        repository=repository,
        registry=registry,
        factory=factory,
        work_root=settings.job_work_root,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
        lock_timeout_minutes=settings.job_lock_timeout_minutes,
    )
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, worker.stop)
    await worker.run_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", required=True, choices=[q.value for q in QueueName])
    arguments = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(async_main(QueueName(arguments.queue)))


if __name__ == "__main__":
    main()
