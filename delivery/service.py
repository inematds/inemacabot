"""Serviço unitário de entrega ao Telegram."""

from __future__ import annotations

from pathlib import Path

from telegram import Bot

from delivery.formatter import format_delivery
from message_utils import split_message
from queueing.job_repository import JobRepository
from queueing.models import Job, JobStatus


class DeliveryService:
    def __init__(
        self,
        *,
        bot: Bot,
        repository: JobRepository,
        work_root: str,
    ) -> None:
        self.bot = bot
        self.repository = repository
        self.work_root = Path(work_root).resolve()

    async def deliver(self, job: Job) -> None:
        last_message_id: str | None = None
        try:
            for chunk in split_message(format_delivery(job)):
                sent = await self.bot.send_message(chat_id=job.chat_id, text=chunk)
                last_message_id = str(sent.message_id)
            if job.status == JobStatus.COMPLETED:
                for path in self._result_files(job):
                    with path.open("rb") as file_handle:
                        sent = await self.bot.send_document(
                            chat_id=job.chat_id,
                            document=file_handle,
                            filename=path.name,
                        )
                    last_message_id = str(sent.message_id)
        except Exception as exc:
            self.repository.mark_delivery_failed(
                job.id, f"{type(exc).__name__}: {exc}"
            )
            raise
        self.repository.mark_delivered(
            job.id, telegram_message_id=last_message_id
        )

    def _result_files(self, job: Job) -> list[Path]:
        if not job.result:
            return []
        raw_files = job.result.get("files", [])
        if not isinstance(raw_files, list):
            return []
        job_root = (self.work_root / job.id).resolve()
        files: list[Path] = []
        for value in raw_files[:10]:
            if not isinstance(value, str):
                continue
            path = Path(value).resolve()
            if path == job_root or job_root not in path.parents:
                continue
            if path.is_file() and path.stat().st_size <= 20 * 1024 * 1024:
                files.append(path)
        return files
