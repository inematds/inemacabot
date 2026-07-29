"""Executor determinístico usado para validar toda a infraestrutura."""

from __future__ import annotations

import asyncio

from agents.base import AgentRequest, AgentResult


class TestQueueExecutor:
    __test__ = False

    def __init__(self, delay_seconds: float = 10) -> None:
        self.delay_seconds = delay_seconds

    async def execute(self, request: AgentRequest) -> AgentResult:
        await asyncio.sleep(self.delay_seconds)
        text = str(request.payload["texto"])
        output_path = request.working_directory / "files" / "resultado.txt"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        return AgentResult(
            success=True,
            result={
                "summary": "Arquivo de teste criado com sucesso.",
                "files": [str(output_path)],
            },
        )
