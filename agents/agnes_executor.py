"""Executor isolado da skill de virtual staging Agnes."""

from __future__ import annotations

import asyncio
import os
import signal
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
        pipeline_script: str | None = None,
    ) -> None:
        self.skills_root = Path(skills_root).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.pipeline_script = (
            Path(pipeline_script).resolve() if pipeline_script else None
        )

    async def execute(self, request: AgentRequest) -> AgentResult:
        source = self.skills_root / "agnes"
        script = source / "rodar.py"
        job_root = request.working_directory.resolve()
        if not script.is_file():
            return AgentResult(success=False, error="A skill Agnes não está instalada.")
        if not os.environ.get("AGNES_API_KEY", "").strip():
            return AgentResult(success=False, error="A integração Agnes não está configurada.")

        runtime_root = job_root / "runtime"
        mode = str(request.payload.get("mode", "short"))
        try:
            runtime_skill = self._prepare_runtime_skill(runtime_root, source)
            command = self._build_command(
                request=request,
                job_root=job_root,
                runtime_root=runtime_root,
                runtime_skill=runtime_skill,
                mode=mode,
            )
        except ValueError as exc:
            return AgentResult(success=False, error=str(exc))
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
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
            return AgentResult(success=False, error="A geração Agnes excedeu o tempo limite.")
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
            raise
        except OSError:
            return AgentResult(success=False, error="Não foi possível iniciar a skill Agnes.")

        (job_root / "agnes-stdout.log").write_bytes(stdout[-self.max_output_bytes :])
        (job_root / "agnes-stderr.log").write_bytes(stderr[-self.max_output_bytes :])
        if process.returncode != 0:
            consistency_error = runtime_root / "output" / "consistency-error.txt"
            if consistency_error.is_file():
                return AgentResult(
                    success=False,
                    error=(
                        "Os estágios foram rejeitados por inconsistência de câmera "
                        "ou arquitetura."
                    ),
                )
            return AgentResult(success=False, error="A Agnes não conseguiu gerar o vídeo.")

        if mode in {"preview", "codex-preview"}:
            return self._preview_result(request.job_id, job_root, runtime_root)
        generated_name = (
            "renovation-video-18s.mp4"
            if mode in {"auto18", "render18", "codex-auto18"}
            else "renovation-video.mp4"
        )
        generated = runtime_root / "output" / generated_name
        if not generated.is_file() or generated.stat().st_size == 0:
            return AgentResult(success=False, error="A Agnes não retornou um vídeo válido.")
        destination = job_root / "files" / generated_name
        shutil.copyfile(generated, destination)
        return AgentResult(
            success=True,
            result={
                "summary": (
                    "Vídeo de reforma em três partes gerado pela Agnes."
                    if mode in {"auto18", "render18", "codex-auto18"}
                    else "Vídeo de reforma gerado pela Agnes."
                ),
                "files": [str(destination)],
            },
        )

    def _build_command(
        self,
        *,
        request: AgentRequest,
        job_root: Path,
        runtime_root: Path,
        runtime_skill: Path,
        mode: str,
    ) -> list[str]:
        if mode == "short":
            image = self._job_file(request.payload.get("image_path"), job_root)
            return [
                sys.executable,
                str(runtime_skill / "rodar.py"),
                "--imagem",
                str(image),
                "--img",
                "agnes",
            ]
        pipeline = self.pipeline_script or runtime_skill / "pipeline_18s.py"
        if not pipeline.is_file():
            raise ValueError("O pipeline Agnes multietapas não está instalado.")
        command = [
            sys.executable,
            str(pipeline),
            "--skill-dir",
            str(runtime_skill),
            "--output-dir",
            str(runtime_root / "output"),
            "--mode",
            mode,
        ]
        if mode in {"preview", "auto18"}:
            image = self._job_file(request.payload.get("image_path"), job_root)
            command.extend(["--image", str(image)])
            return command
        if mode == "render18":
            values = request.payload.get("stage_paths")
            if not isinstance(values, list) or len(values) != 4:
                raise ValueError("Os quatro estágios aprovados são obrigatórios.")
            stages = [self._job_file(value, job_root) for value in values]
            command.extend(["--stages", *(str(path) for path in stages)])
            return command
        raise ValueError("Modo de geração Agnes inválido.")

    @staticmethod
    def _prepare_runtime_skill(runtime_root: Path, source: Path) -> Path:
        runtime_skill = runtime_root / "skills" / "agnes"
        shutil.copytree(source, runtime_skill, dirs_exist_ok=True)
        return runtime_skill

    @staticmethod
    def _job_file(value: object, job_root: Path) -> Path:
        path = Path(str(value)).resolve()
        if job_root not in path.parents or not path.is_file():
            raise ValueError("Um arquivo do job é inválido.")
        return path

    @staticmethod
    def _preview_result(
        job_id: str, job_root: Path, runtime_root: Path
    ) -> AgentResult:
        stage_files: list[str] = []
        for index in range(1, 4):
            source = runtime_root / "output" / f"stage-{index}.png"
            if not source.is_file() or source.stat().st_size == 0:
                return AgentResult(
                    success=False,
                    error="A Agnes não retornou todos os estágios.",
                )
            destination = job_root / "files" / source.name
            shutil.copyfile(source, destination)
            stage_files.append(str(destination))
        reference = runtime_root / "output" / "stage-4-final-reference.png"
        if not reference.is_file() or reference.stat().st_size == 0:
            return AgentResult(
                success=False,
                error="A Agnes não preservou a imagem final de referência.",
            )
        destination = job_root / "files" / reference.name
        shutil.copyfile(reference, destination)
        stage_files.append(str(destination))
        contact = runtime_root / "output" / "approval-contact-sheet.jpg"
        if not contact.is_file() or contact.stat().st_size == 0:
            return AgentResult(
                success=False,
                error="A Agnes não criou a comparação dos estágios.",
            )
        contact_destination = job_root / "files" / contact.name
        shutil.copyfile(contact, contact_destination)
        warning = runtime_root / "output" / "consistency-warning.txt"
        if warning.is_file():
            summary = (
                "Estágios gerados. A melhor tentativa foi aceita com aviso de "
                "consistência; confira atentamente a imagem comparativa e use "
                f"/aprovarvideo {job_id} se estiver adequada."
            )
        else:
            summary = (
                "Estágios aprovados pela validação automática. Confira a imagem "
                "comparativa e use "
                f"/aprovarvideo {job_id} para criar o vídeo com trabalhadores."
            )
        return AgentResult(
            success=True,
            result={
                "summary": summary,
                "files": [str(contact_destination), *stage_files],
                "stage_files": stage_files,
            },
        )
