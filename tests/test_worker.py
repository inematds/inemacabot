import asyncio
import tempfile
import unittest
from pathlib import Path

from agents.factory import AgentFactory
from queueing.job_repository import JobRepository
from queueing.models import JobStatus, QueueName
from skills.registry import SkillRegistry
from workers.worker import QueueWorker


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.repository = JobRepository(str(root / "queue.sqlite3"))
        self.repository.migrate()
        self.registry = SkillRegistry.from_file(
            Path(__file__).parents[1] / "skills" / "registry.json"
        )
        self.worker = QueueWorker(
            queue=QueueName.SERVICOS,
            repository=self.repository,
            registry=self.registry,
            factory=AgentFactory(
                codex_binary="codex",
                codex_model=None,
                timeout_seconds=10,
                test_delay_seconds=0.01,
            ),
            work_root=str(root / "jobs"),
            poll_interval_seconds=0.01,
            lock_timeout_minutes=30,
            worker_id="worker-test",
        )

    async def asyncTearDown(self) -> None:
        self.temporary.cleanup()

    async def test_processes_test_skill_and_creates_file(self) -> None:
        created = self.repository.create_job(
            queue=QueueName.SERVICOS,
            skill="teste-fila",
            payload={"texto": "resultado esperado"},
            user_id="123",
            chat_id="456",
        )
        claimed = self.repository.claim_next_job(
            QueueName.SERVICOS, "worker-test"
        )
        await self.worker.process_job(claimed)

        completed = self.repository.get_job(created.id)
        self.assertEqual(completed.status, JobStatus.COMPLETED)
        output = Path(completed.result["files"][0])
        self.assertEqual(output.read_text(encoding="utf-8"), "resultado esperado")

    async def test_running_job_can_be_cancelled(self) -> None:
        self.worker.factory.test_delay_seconds = 5
        created = self.repository.create_job(
            queue=QueueName.SERVICOS,
            skill="teste-fila",
            payload={"texto": "cancelar"},
            user_id="123",
            chat_id="456",
        )
        claimed = self.repository.claim_next_job(
            QueueName.SERVICOS, "worker-test"
        )
        task = asyncio.create_task(self.worker.process_job(claimed))
        await asyncio.sleep(0.05)
        self.repository.cancel_job(created.id, "123")
        await asyncio.wait_for(task, timeout=2)
        self.assertEqual(
            self.repository.get_job(created.id).status, JobStatus.CANCELLED
        )


if __name__ == "__main__":
    unittest.main()
