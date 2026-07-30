"""Executor Codex isolado para jobs textuais."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from agents.base import AgentRequest, AgentResult


class CodexAgentExecutor:
    def __init__(
        self,
        *,
        binary: str,
        model: str | None,
        timeout_seconds: int,
        max_output_bytes: int = 1_000_000,
    ) -> None:
        self.binary = binary
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    async def execute(self, request: AgentRequest) -> AgentResult:
        output_path = request.working_directory / "output.md"
        stdout_path = request.working_directory / "stdout.log"
        stderr_path = request.working_directory / "stderr.log"
        prompt = "\n".join(
            [
                "Execute uma única tarefa do InemacaBot.",
                "Trabalhe somente com os dados fornecidos.",
                "Não acesse arquivos fora do diretório de trabalho.",
                "Não exponha credenciais nem tente descobrir segredos.",
                "Retorne somente o conteúdo final destinado ao usuário.",
                "",
                f"Skill: {request.skill}",
                f"Instrução: {request.instruction}",
                "Payload:",
                json.dumps(request.payload, ensure_ascii=False, indent=2),
            ]
        )
        command = [
            self.binary,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "workspace-write",
            "--color",
            "never",
            "--cd",
            str(request.working_directory),
            "--output-last-message",
            str(output_path),
        ]
        if self.model:
            command.extend(["--model", self.model])
        command.append("-")
        environment = {
            name: value
            for name, value in os.environ.items()
            if name
            in {
                "PATH",
                "HOME",
                "USER",
                "LOGNAME",
                "LANG",
                "LC_ALL",
                "TERM",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "CODEX_HOME",
            }
        }
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            process.stdin.write(prompt.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
            stdout_task = asyncio.create_task(
                _read_limited(process.stdout, self.max_output_bytes)
            )
            stderr_task = asyncio.create_task(
                _read_limited(process.stderr, self.max_output_bytes)
            )
            await asyncio.wait_for(process.wait(), timeout=self.timeout_seconds)
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        except TimeoutError:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            for task_name in ("stdout_task", "stderr_task"):
                task = locals().get(task_name)
                if task is not None:
                    task.cancel()
            await _settle_reader_tasks(locals())
            return AgentResult(success=False, error="O agente excedeu o tempo limite.")
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            for task_name in ("stdout_task", "stderr_task"):
                task = locals().get(task_name)
                if task is not None:
                    task.cancel()
            await _settle_reader_tasks(locals())
            raise
        except OSError:
            return AgentResult(success=False, error="Não foi possível iniciar o agente.")

        stdout_path.write_bytes(stdout[-self.max_output_bytes :])
        stderr_path.write_bytes(stderr[-self.max_output_bytes :])
        if process.returncode != 0:
            return AgentResult(
                success=False,
                error=f"O agente terminou com código {process.returncode}.",
            )
        try:
            answer = output_path.read_text(encoding="utf-8").strip()
        except OSError:
            return AgentResult(success=False, error="O agente não gerou resultado.")
        if not answer:
            return AgentResult(success=False, error="O resultado do agente está vazio.")
        if len(answer.encode("utf-8")) > self.max_output_bytes:
            return AgentResult(success=False, error="O resultado excede o limite.")
        return AgentResult(
            success=True,
            result={
                "summary": answer,
                "files": [str(output_path)],
            },
        )


async def _read_limited(
    stream: asyncio.StreamReader, limit: int
) -> bytes:
    retained = bytearray()
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            break
        retained.extend(chunk)
        if len(retained) > limit:
            del retained[: len(retained) - limit]
    return bytes(retained)


async def _settle_reader_tasks(local_values: dict[str, object]) -> None:
    tasks = [
        task
        for name in ("stdout_task", "stderr_task")
        if isinstance((task := local_values.get(name)), asyncio.Task)
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
