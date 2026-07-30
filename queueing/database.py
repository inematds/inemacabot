"""Conexões e migrations SQLite."""

from __future__ import annotations

import sqlite3
from pathlib import Path


MIGRATION_VERSION = 1
MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    queue TEXT NOT NULL CHECK (queue IN ('videos', 'textos', 'servicos')),
    skill TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    user_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    source_message_id TEXT,
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    available_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    cancel_requested_at TEXT,
    locked_by TEXT,
    locked_at TEXT,
    delivery_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (delivery_status IN ('pending', 'delivering', 'delivered', 'failed')),
    delivered_at TEXT,
    delivery_attempts INTEGER NOT NULL DEFAULT 0 CHECK (delivery_attempts >= 0),
    delivery_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_claim
ON jobs(queue, status, available_at, priority DESC, created_at ASC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_running_per_queue
ON jobs(queue) WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_jobs_user
ON jobs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_delivery
ON jobs(delivery_status, completed_at);

CREATE INDEX IF NOT EXISTS idx_jobs_lock
ON jobs(locked_at);

CREATE TABLE IF NOT EXISTS workers (
    worker_id TEXT PRIMARY KEY,
    queue TEXT NOT NULL CHECK (queue IN ('videos', 'textos', 'servicos')),
    status TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    current_job_id TEXT,
    started_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    telegram_message_id TEXT,
    error TEXT,
    UNIQUE(job_id, attempt)
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=5,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript(MIGRATION_SQL)
            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations(version, applied_at)
                VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (MIGRATION_VERSION,),
            )
