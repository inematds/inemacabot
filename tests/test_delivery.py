import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from delivery.service import DeliveryService
from queueing.job_repository import JobRepository
from queueing.models import DeliveryStatus, QueueName


class FakeBot:
    def __init__(self) -> None:
        self.messages = []
        self.documents = []

    async def send_message(self, *, chat_id, text):
        self.messages.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.messages))

    async def send_document(self, *, chat_id, document, filename):
        self.documents.append((chat_id, filename, document.read()))
        return SimpleNamespace(message_id=100 + len(self.documents))


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.work_root = root / "jobs"
        self.repository = JobRepository(str(root / "queue.sqlite3"))
        self.repository.migrate()
        created = self.repository.create_job(
            queue=QueueName.SERVICOS,
            skill="teste-fila",
            payload={"texto": "teste"},
            user_id="123",
            chat_id="456",
        )
        running = self.repository.claim_next_job(
            QueueName.SERVICOS, "worker"
        )
        job_root = self.work_root / created.id / "files"
        job_root.mkdir(parents=True)
        output = job_root / "resultado.txt"
        output.write_text("conteúdo", encoding="utf-8")
        self.repository.complete_job(
            running.id,
            "worker",
            {"summary": "pronto", "files": [str(output)]},
        )

    async def asyncTearDown(self) -> None:
        self.temporary.cleanup()

    async def test_delivers_message_and_file_once(self) -> None:
        bot = FakeBot()
        service = DeliveryService(
            bot=bot,
            repository=self.repository,
            work_root=str(self.work_root),
        )
        job = self.repository.claim_delivery(max_attempts=3)
        await service.deliver(job)

        self.assertEqual(len(bot.messages), 1)
        self.assertEqual(len(bot.documents), 1)
        self.assertEqual(
            self.repository.get_job(job.id).delivery_status,
            DeliveryStatus.DELIVERED,
        )
        self.assertIsNone(self.repository.claim_delivery(max_attempts=3))


if __name__ == "__main__":
    unittest.main()
