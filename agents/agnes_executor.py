"""Executor isolado da skill de virtual staging Agnes."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

from agents.base import AgentRequest, AgentResult


class AgnesVirtualStagingExecutor:
    def __init__(
        self,
        *,
        skills_root: str,
        timeout_seconds: int,
        max_output_bytes: int = 1_000_000,
    ) -> None:
        self.skills_root = Path(skills_root).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    async def execute(self, request: AgentRequest) -> AgentResult:
        source = self.skills_root / "agnes"
        script = source / "rodar.py"
        image = Path(str(request.payload["image_path"])).resolve()
        job_root = request.working_directory.resolve()
        if job_root not in image.parents or not image.is_file():
            return AgentResult(success=False, error="A imagem do job é inválida.")
        if not script.is_file():
            return AgentResult(success=False, error="A skill Agnes não está instalada.")
        if not os.environ.get("AGNES_API_KEY", "").strip():
            return AgentResult(success=False, error="A integração Agnes não está configurada.")

        runtime_root = job_root / "runtime"
        runtime_skill = runtime_root / "skills" / "agnes"
        shutil.copytree(source, runtime_skill, dirs_exist_ok=True)
        command = [
            sys.executable,
            str(runtime_skill / "rodar.py"),
            "--imagem",
            str(image),
            "--img",
            "agnes",
        ]
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
                start_new_session=True,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except TimeoutError:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            return AgentResult(success=False, error="A geração Agnes excedeu o tempo limite.")
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            raise
        except OSError:
            return AgentResult(success=False, error="Não foi possível iniciar a skill Agnes.")

        (job_root / "agnes-stdout.log").write_bytes(stdout[-self.max_output_bytes :])
        (job_root / "agnes-stderr.log").write_bytes(stderr[-self.max_output_bytes :])
        if process.returncode != 0:
            return AgentResult(success=False, error="A Agnes não conseguiu gerar o vídeo.")

        generated = runtime_root / "output" / "renovation-video.mp4"
        if not generated.is_file() or generated.stat().st_size == 0:
            return AgentResult(success=False, error="A Agnes não retornou um vídeo válido.")
        destination = job_root / "files" / "renovation-video.mp4"
        shutil.copyfile(generated, destination)
        return AgentResult(
            success=True,
            result={
                "summary": "Vídeo de reforma gerado pela Agnes.",
                "files": [str(destination)],
            },
        )
