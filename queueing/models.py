"""Modelos centrais dos jobs."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class QueueName(StrEnum):
    VIDEOS = "videos"
    TEXTOS = "textos"
    SERVICOS = "servicos"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    queue: QueueName
    skill: str
    payload: dict[str, Any]
    status: JobStatus
    priority: int
    attempts: int
    max_attempts: int
    user_id: str
    chat_id: str
    source_message_id: str | None
    progress: int
    result: dict[str, Any] | None
    error: str | None
    created_at: str
    available_at: str
    started_at: str | None
    completed_at: str | None
    cancel_requested_at: str | None
    locked_by: str | None
    locked_at: str | None
    delivery_status: DeliveryStatus
    delivered_at: str | None
    delivery_attempts: int
    delivery_error: str | None


def generate_job_id() -> str:
    return f"job_{uuid.uuid4().hex}"


def encode_json(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"))


def decode_json(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("O JSON persistido deve ser um objeto.")
    return decoded
