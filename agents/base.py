"""Contratos independentes de provedor para executores."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AgentRequest:
    job_id: str
    skill: str
    payload: dict[str, Any]
    instruction: str
    working_directory: Path


@dataclass(frozen=True, slots=True)
class AgentResult:
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None


class AgentExecutor(Protocol):
    async def execute(self, request: AgentRequest) -> AgentResult: ...
