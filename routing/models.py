"""Modelos das decisões de roteamento."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from queueing.models import QueueName


class RouteAction(StrEnum):
    REPLY = "reply"
    CLARIFY = "clarify"
    ENQUEUE = "enqueue"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    action: RouteAction
    response: str | None = None
    question: str | None = None
    queue: QueueName | None = None
    skill: str | None = None
    payload: dict[str, Any] | None = None
