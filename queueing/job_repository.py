"""Repositório transacional de jobs."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from queueing.database import Database
from queueing.models import (
    DeliveryStatus,
    Job,
    JobStatus,
    QueueName,
    decode_json,
    encode_json,
    generate_job_id,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def timestamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="milliseconds")


class JobRepository:
    def __init__(self, database_path: str) -> None:
        self.database = Database(database_path)

    def migrate(self) -> None:
        self.database.migrate()

    def create_job(
        self,
        *,
        queue: QueueName | str,
        skill: str,
        payload: dict[str, Any],
        user_id: str,
        chat_id: str,
        source_message_id: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        job_id: str | None = None,
    ) -> Job:
        queue_name = QueueName(queue)
        if not skill.strip():
            raise ValueError("A skill não pode estar vazia.")
        if max_attempts <= 0:
            raise ValueError("max_attempts deve ser maior que zero.")
        if priority not in (0, 10, 20):
            raise ValueError("Prioridade inválida.")
        now = timestamp()
        identifier = job_id or generate_job_id()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, queue, skill, payload, status, priority, attempts,
                    max_attempts, user_id, chat_id, source_message_id, progress,
                    created_at, available_at, delivery_status
                ) VALUES (?, ?, ?, ?, 'pending', ?, 0, ?, ?, ?, ?, 0, ?, ?, 'pending')
                """,
                (
                    identifier,
                    queue_name.value,
                    skill.strip(),
                    encode_json(payload),
                    priority,
                    max_attempts,
                    str(user_id),
                    str(chat_id),
                    source_message_id,
                    now,
                    now,
                ),
            )
        job = self.get_job(identifier)
        assert job is not None
        return job

    def get_job(self, job_id: str, *, user_id: str | None = None) -> Job | None:
        sql = "SELECT * FROM jobs WHERE id = ?"
        parameters: list[Any] = [job_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            parameters.append(str(user_id))
        with self.database.connect() as connection:
            row = connection.execute(sql, parameters).fetchone()
        return self._to_job(row) if row else None

    def get_jobs_by_user(self, user_id: str, *, limit: int = 10) -> list[Job]:
        if limit <= 0 or limit > 100:
            raise ValueError("limit deve estar entre 1 e 100.")
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM jobs
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (str(user_id), limit),
            ).fetchall()
        return [self._to_job(row) for row in rows]

    def claim_next_job(self, queue: QueueName | str, worker_id: str) -> Job | None:
        queue_name = QueueName(queue)
        now = timestamp()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            running = connection.execute(
                "SELECT 1 FROM jobs WHERE queue = ? AND status = 'running' LIMIT 1",
                (queue_name.value,),
            ).fetchone()
            if running:
                connection.execute("ROLLBACK")
                return None
            row = connection.execute(
                """
                SELECT id FROM jobs
                WHERE queue = ?
                  AND status = 'pending'
                  AND available_at <= ?
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
                """,
                (queue_name.value, now),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                return None
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    attempts = attempts + 1,
                    started_at = ?,
                    locked_by = ?,
                    locked_at = ?,
                    progress = CASE WHEN progress < 1 THEN 1 ELSE progress END,
                    error = NULL
                WHERE id = ? AND status = 'pending'
                """,
                (now, worker_id, now, row["id"]),
            )
            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                return None
            claimed = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (row["id"],)
            ).fetchone()
            connection.execute("COMMIT")
            return self._to_job(claimed)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def update_job_progress(
        self, job_id: str, worker_id: str, progress: int
    ) -> bool:
        if not 0 <= progress <= 100:
            raise ValueError("O progresso deve estar entre 0 e 100.")
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET progress = ?, locked_at = ?
                WHERE id = ? AND status = 'running' AND locked_by = ?
                """,
                (progress, timestamp(), job_id, worker_id),
            )
        return cursor.rowcount == 1

    def complete_job(
        self, job_id: str, worker_id: str, result: dict[str, Any]
    ) -> bool:
        now = timestamp()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'completed', result = ?, progress = 100,
                    completed_at = ?, locked_by = NULL, locked_at = NULL,
                    cancel_requested_at = NULL
                WHERE id = ? AND status = 'running' AND locked_by = ?
                """,
                (encode_json(result), now, job_id, worker_id),
            )
        return cursor.rowcount == 1

    def fail_job(
        self,
        job_id: str,
        worker_id: str,
        error: str,
        *,
        retry_delays: Iterable[int] = (30, 120),
    ) -> Job | None:
        job = self.get_job(job_id)
        if job is None or job.status != JobStatus.RUNNING or job.locked_by != worker_id:
            return None
        delays = tuple(retry_delays)
        should_retry = job.attempts < job.max_attempts
        now = utc_now()
        if should_retry:
            delay_index = min(max(job.attempts - 1, 0), max(len(delays) - 1, 0))
            delay = delays[delay_index] if delays else 0
            status_value = JobStatus.PENDING.value
            available_at = timestamp(now + timedelta(seconds=delay))
            completed_at = None
            progress = 0
        else:
            status_value = JobStatus.FAILED.value
            available_at = job.available_at
            completed_at = timestamp(now)
            progress = job.progress
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, available_at = ?, completed_at = ?, progress = ?,
                    error = ?, locked_by = NULL, locked_at = NULL
                WHERE id = ? AND status = 'running' AND locked_by = ?
                """,
                (
                    status_value,
                    available_at,
                    completed_at,
                    progress,
                    error[:2000],
                    job_id,
                    worker_id,
                ),
            )
        return self.get_job(job_id) if cursor.rowcount == 1 else None

    def cancel_job(self, job_id: str, user_id: str) -> Job | None:
        now = timestamp()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ? AND user_id = ?",
                (job_id, str(user_id)),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                return None
            if row["status"] == JobStatus.PENDING.value:
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled', completed_at = ?, delivery_status = 'pending'
                    WHERE id = ?
                    """,
                    (now, job_id),
                )
            elif row["status"] == JobStatus.RUNNING.value:
                connection.execute(
                    "UPDATE jobs SET cancel_requested_at = ? WHERE id = ?",
                    (now, job_id),
                )
            connection.execute("COMMIT")
        return self.get_job(job_id, user_id=str(user_id))

    def mark_cancelled(self, job_id: str, worker_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', completed_at = ?, locked_by = NULL,
                    locked_at = NULL
                WHERE id = ? AND status = 'running' AND locked_by = ?
                """,
                (timestamp(), job_id, worker_id),
            )
        return cursor.rowcount == 1

    def is_cancel_requested(self, job_id: str, worker_id: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT cancel_requested_at FROM jobs
                WHERE id = ? AND status = 'running' AND locked_by = ?
                """,
                (job_id, worker_id),
            ).fetchone()
        return bool(row and row["cancel_requested_at"])

    def retry_job(self, job_id: str, user_id: str) -> Job | None:
        original = self.get_job(job_id, user_id=str(user_id))
        if original is None or original.status not in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }:
            return None
        return self.create_job(
            queue=original.queue,
            skill=original.skill,
            payload=original.payload,
            user_id=original.user_id,
            chat_id=original.chat_id,
            source_message_id=original.source_message_id,
            priority=original.priority,
            max_attempts=original.max_attempts,
        )

    def release_expired_locks(self, timeout_minutes: int) -> int:
        cutoff = timestamp(utc_now() - timedelta(minutes=timeout_minutes))
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, locked_by FROM jobs
                WHERE status = 'running' AND locked_at < ?
                """,
                (cutoff,),
            ).fetchall()
        recovered = 0
        for row in rows:
            result = self.fail_job(
                row["id"],
                row["locked_by"],
                "Lock expirado; job recuperado após interrupção.",
                retry_delays=(0,),
            )
            recovered += int(result is not None)
        return recovered

    def get_queue_stats(self) -> dict[str, dict[str, int]]:
        stats = {
            queue.value: {status.value: 0 for status in JobStatus}
            for queue in QueueName
        }
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT queue, status, COUNT(*) AS total FROM jobs GROUP BY queue, status"
            ).fetchall()
        for row in rows:
            stats[row["queue"]][row["status"]] = row["total"]
        return stats

    def get_queue_position(self, job_id: str) -> int | None:
        job = self.get_job(job_id)
        if job is None or job.status != JobStatus.PENDING:
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total FROM jobs
                WHERE queue = ?
                  AND status = 'pending'
                  AND available_at <= ?
                  AND (
                    priority > ?
                    OR (priority = ? AND created_at <= ?)
                  )
                """,
                (
                    job.queue.value,
                    timestamp(),
                    job.priority,
                    job.priority,
                    job.created_at,
                ),
            ).fetchone()
        return int(row["total"])

    def heartbeat(
        self,
        worker_id: str,
        queue: QueueName | str,
        *,
        status: str,
        current_job_id: str | None,
    ) -> None:
        now = timestamp()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workers(
                    worker_id, queue, status, last_seen_at, current_job_id, started_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    queue = excluded.queue,
                    status = excluded.status,
                    last_seen_at = excluded.last_seen_at,
                    current_job_id = excluded.current_job_id
                """,
                (
                    worker_id,
                    QueueName(queue).value,
                    status,
                    now,
                    current_job_id,
                    now,
                ),
            )

    def get_workers(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workers ORDER BY queue, worker_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def has_recent_worker(
        self, queue: QueueName | str, *, max_age_seconds: int = 30
    ) -> bool:
        cutoff = timestamp(utc_now() - timedelta(seconds=max_age_seconds))
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM workers
                WHERE queue = ? AND last_seen_at >= ?
                LIMIT 1
                """,
                (QueueName(queue).value, cutoff),
            ).fetchone()
        return row is not None

    def claim_delivery(
        self, *, max_attempts: int, lease_minutes: int = 5
    ) -> Job | None:
        now = timestamp()
        stale = timestamp(utc_now() - timedelta(minutes=lease_minutes))
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE jobs
                SET delivery_status = 'failed',
                    delivery_error = 'Lease de entrega expirado.'
                WHERE delivery_status = 'delivering'
                  AND locked_at < ?
                """,
                (stale,),
            )
            row = connection.execute(
                """
                SELECT id FROM jobs
                WHERE status IN ('completed', 'failed', 'cancelled')
                  AND delivery_status IN ('pending', 'failed')
                  AND delivery_attempts < ?
                ORDER BY completed_at ASC, created_at ASC
                LIMIT 1
                """,
                (max_attempts,),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                return None
            cursor = connection.execute(
                """
                UPDATE jobs
                SET delivery_status = 'delivering',
                    delivery_attempts = delivery_attempts + 1,
                    delivery_error = NULL,
                    locked_at = ?
                WHERE id = ? AND delivery_status IN ('pending', 'failed')
                """,
                (now, row["id"]),
            )
            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                return None
            claimed = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (row["id"],)
            ).fetchone()
            connection.execute(
                """
                INSERT INTO deliveries(id, job_id, attempt, status, started_at)
                VALUES (?, ?, ?, 'delivering', ?)
                """,
                (
                    f"delivery_{uuid.uuid4().hex}",
                    row["id"],
                    claimed["delivery_attempts"],
                    now,
                ),
            )
            connection.execute("COMMIT")
            return self._to_job(claimed)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def mark_delivered(
        self, job_id: str, *, telegram_message_id: str | None = None
    ) -> bool:
        now = timestamp()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE jobs
                SET delivery_status = 'delivered', delivered_at = ?,
                    delivery_error = NULL, locked_at = NULL
                WHERE id = ? AND delivery_status = 'delivering'
                """,
                (now, job_id),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    UPDATE deliveries
                    SET status = 'delivered', completed_at = ?,
                        telegram_message_id = ?
                    WHERE job_id = ? AND status = 'delivering'
                    """,
                    (now, telegram_message_id, job_id),
                )
            connection.execute("COMMIT")
        return cursor.rowcount == 1

    def mark_delivery_failed(self, job_id: str, error: str) -> bool:
        now = timestamp()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE jobs
                SET delivery_status = 'failed', delivery_error = ?, locked_at = NULL
                WHERE id = ? AND delivery_status = 'delivering'
                """,
                (error[:2000], job_id),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    UPDATE deliveries
                    SET status = 'failed', completed_at = ?, error = ?
                    WHERE job_id = ? AND status = 'delivering'
                    """,
                    (now, error[:2000], job_id),
                )
            connection.execute("COMMIT")
        return cursor.rowcount == 1

    @staticmethod
    def _to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            queue=QueueName(row["queue"]),
            skill=row["skill"],
            payload=decode_json(row["payload"]) or {},
            status=JobStatus(row["status"]),
            priority=row["priority"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            source_message_id=row["source_message_id"],
            progress=row["progress"],
            result=decode_json(row["result"]),
            error=row["error"],
            created_at=row["created_at"],
            available_at=row["available_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            cancel_requested_at=row["cancel_requested_at"],
            locked_by=row["locked_by"],
            locked_at=row["locked_at"],
            delivery_status=DeliveryStatus(row["delivery_status"]),
            delivered_at=row["delivered_at"],
            delivery_attempts=row["delivery_attempts"],
            delivery_error=row["delivery_error"],
        )
