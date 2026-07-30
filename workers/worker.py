"""Worker genérico, limitado a uma fila por processo."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from agents.base import AgentRequest
from agents.factory import AgentFactory
from queueing.job_repository import JobRepository
from queueing.models import Job, QueueName
from skills.registry import SkillRegistry


LOGGER = logging.getLogger(__name__)


class QueueWorker:
    def __init__(
        self,
        *,
        queue: QueueName,
        repository: JobRepository,
        registry: SkillRegistry,
        factory: AgentFactory,
        work_root: str,
        poll_interval_seconds: float,
        lock_timeout_minutes: int,
        worker_id: str | None = None,
    ) -> None:
        self.queue = queue
        self.repository = repository
        self.registry = registry
        self.factory = factory
        self.work_root = Path(work_root).resolve()
        self.poll_interval_seconds = poll_interval_seconds
        self.lock_timeout_minutes = lock_timeout_minutes
        self.worker_id = worker_id or f"{queue.value}-{uuid.uuid4().hex[:12]}"
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run_forever(self) -> None:
        self.repository.release_expired_locks(self.lock_timeout_minutes)
        while not self._stopping.is_set():
            self.repository.heartbeat(
                self.worker_id,
                self.queue,
                status="idle",
                current_job_id=None,
            )
            job = self.repository.claim_next_job(self.queue, self.worker_id)
            if job is None:
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(),
                        timeout=self.poll_interval_seconds,
                    )
                except TimeoutError:
                    pass
                continue
            await self.process_job(job)

    async def process_job(self, job: Job) -> None:
        started = asyncio.get_running_loop().time()
        self.repository.heartbeat(
            self.worker_id,
            self.queue,
            status="running",
            current_job_id=job.id,
        )
        try:
            skill = self.registry.validate_payload(job.skill, job.payload)
            if skill.queue != self.queue:
                raise ValueError("A skill não pertence à fila do worker.")
            work_directory = self._prepare_directory(job)
            executor = self.factory.create(skill)
            self.repository.update_job_progress(job.id, self.worker_id, 10)
            execution = asyncio.create_task(
                executor.execute(
                    AgentRequest(
                        job_id=job.id,
                        skill=job.skill,
                        payload=job.payload,
                        instruction=skill.instruction,
                        working_directory=work_directory,
                    )
                )
            )
            while not execution.done():
                if self.repository.is_cancel_requested(job.id, self.worker_id):
                    execution.cancel()
                    try:
                        await execution
                    except asyncio.CancelledError:
                        pass
                    self.repository.mark_cancelled(job.id, self.worker_id)
                    return
                self.repository.update_job_progress(job.id, self.worker_id, 50)
                self.repository.heartbeat(
                    self.worker_id,
                    self.queue,
                    status="running",
                    current_job_id=job.id,
                )
                try:
                    await asyncio.wait_for(asyncio.shield(execution), timeout=1)
                except TimeoutError:
                    continue
            result = await execution
            if result.success and result.result is not None:
                self.repository.complete_job(job.id, self.worker_id, result.result)
            else:
                self.repository.fail_job(
                    job.id,
                    self.worker_id,
                    result.error or "Falha desconhecida no executor.",
                )
        except asyncio.CancelledError:
            self.repository.fail_job(
                job.id,
                self.worker_id,
                "Worker interrompido durante a execução.",
                retry_delays=(0,),
            )
            raise
        except Exception as exc:
            LOGGER.exception(
                "Falha no job.",
                extra={
                    "job_id": job.id,
                    "queue": self.queue.value,
                    "skill": job.skill,
                    "worker_id": self.worker_id,
                },
            )
            self.repository.fail_job(
                job.id,
                self.worker_id,
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            duration = asyncio.get_running_loop().time() - started
            LOGGER.info(
                "Processamento encerrado em %.3fs.",
                duration,
                extra={
                    "job_id": job.id,
                    "queue": self.queue.value,
                    "skill": job.skill,
                    "worker_id": self.worker_id,
                },
            )
            self.repository.heartbeat(
                self.worker_id,
                self.queue,
                status="idle",
                current_job_id=None,
            )

    def _prepare_directory(self, job: Job) -> Path:
        directory = (self.work_root / job.id).resolve()
        if directory.parent != self.work_root:
            raise ValueError("Diretório de job inválido.")
        (directory / "files").mkdir(parents=True, exist_ok=True)
        input_path = directory / "input.json"
        input_path.write_text(
            json.dumps(
                {
                    "jobId": job.id,
                    "queue": job.queue.value,
                    "skill": job.skill,
                    "payload": job.payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return directory
