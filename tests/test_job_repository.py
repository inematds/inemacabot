import concurrent.futures
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from queueing.job_repository import JobRepository
from queueing.models import DeliveryStatus, JobStatus, QueueName


class JobRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = str(Path(self.temporary.name) / "queue.sqlite3")
        self.repository = JobRepository(self.database_path)
        self.repository.migrate()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_job(
        self,
        *,
        queue: QueueName = QueueName.SERVICOS,
        priority: int = 0,
        max_attempts: int = 3,
    ):
        return self.repository.create_job(
            queue=queue,
            skill="teste-fila",
            payload={"texto": "teste"},
            user_id="123",
            chat_id="456",
            priority=priority,
            max_attempts=max_attempts,
        )

    def test_migration_is_idempotent(self) -> None:
        self.repository.migrate()
        self.create_job()
        self.assertEqual(len(self.repository.get_jobs_by_user("123")), 1)

    def test_claim_uses_priority_and_allows_only_one_running_per_queue(self) -> None:
        normal = self.create_job(priority=0)
        urgent = self.create_job(priority=20)

        claimed = self.repository.claim_next_job(
            QueueName.SERVICOS, "worker-1"
        )
        self.assertEqual(claimed.id, urgent.id)
        self.assertEqual(claimed.attempts, 1)
        self.assertIsNone(
            self.repository.claim_next_job(QueueName.SERVICOS, "worker-2")
        )

        self.repository.complete_job(claimed.id, "worker-1", {"summary": "ok"})
        next_job = self.repository.claim_next_job(
            QueueName.SERVICOS, "worker-2"
        )
        self.assertEqual(next_job.id, normal.id)

    def test_two_connections_never_claim_same_job(self) -> None:
        expected = self.create_job()

        def claim(worker: str):
            repository = JobRepository(self.database_path)
            return repository.claim_next_job(QueueName.SERVICOS, worker)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, ("worker-a", "worker-b")))

        claimed = [job for job in results if job is not None]
        self.assertEqual([job.id for job in claimed], [expected.id])

    def test_different_queues_can_be_claimed_simultaneously(self) -> None:
        for queue in QueueName:
            self.create_job(queue=queue)
        claimed = [
            self.repository.claim_next_job(queue, f"worker-{queue.value}")
            for queue in QueueName
        ]
        self.assertEqual({job.queue for job in claimed}, set(QueueName))

    def test_reports_position_and_recent_worker(self) -> None:
        first = self.create_job()
        second = self.create_job()
        self.assertEqual(self.repository.get_queue_position(first.id), 1)
        self.assertEqual(self.repository.get_queue_position(second.id), 2)
        self.assertFalse(
            self.repository.has_recent_worker(QueueName.SERVICOS)
        )
        self.repository.heartbeat(
            "worker", QueueName.SERVICOS, status="idle", current_job_id=None
        )
        self.assertTrue(
            self.repository.has_recent_worker(QueueName.SERVICOS)
        )

    def test_retry_then_definitive_failure(self) -> None:
        job = self.create_job(max_attempts=2)
        first = self.repository.claim_next_job(QueueName.SERVICOS, "worker")
        retried = self.repository.fail_job(
            first.id, "worker", "transitório", retry_delays=(0,)
        )
        self.assertEqual(retried.status, JobStatus.PENDING)

        second = self.repository.claim_next_job(QueueName.SERVICOS, "worker")
        failed = self.repository.fail_job(
            second.id, "worker", "definitivo", retry_delays=(0,)
        )
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(failed.attempts, 2)

    def test_cancel_checks_owner(self) -> None:
        job = self.create_job()
        self.assertIsNone(self.repository.cancel_job(job.id, "outro"))
        cancelled = self.repository.cancel_job(job.id, "123")
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)

    def test_release_expired_lock_recovers_job(self) -> None:
        job = self.create_job()
        self.repository.claim_next_job(QueueName.SERVICOS, "worker")
        old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        with self.repository.database.connect() as connection:
            connection.execute(
                "UPDATE jobs SET locked_at = ? WHERE id = ?", (old, job.id)
            )
        self.assertEqual(self.repository.release_expired_locks(30), 1)
        self.assertEqual(self.repository.get_job(job.id).status, JobStatus.PENDING)

    def test_delivery_is_claimed_and_marked(self) -> None:
        job = self.create_job()
        running = self.repository.claim_next_job(QueueName.SERVICOS, "worker")
        self.repository.complete_job(running.id, "worker", {"summary": "ok"})

        delivery = self.repository.claim_delivery(max_attempts=3)
        self.assertEqual(delivery.id, job.id)
        self.assertEqual(delivery.delivery_status, DeliveryStatus.DELIVERING)
        self.assertTrue(
            self.repository.mark_delivered(
                delivery.id, telegram_message_id="999"
            )
        )
        self.assertEqual(
            self.repository.get_job(job.id).delivery_status,
            DeliveryStatus.DELIVERED,
        )


if __name__ == "__main__":
    unittest.main()
