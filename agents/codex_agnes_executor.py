"""Executor da skill com imagens Codex e vídeos Agnes."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from agents.agnes_executor import AgnesVirtualStagingExecutor
from agents.base import AgentRequest


class CodexAgnesVirtualStagingExecutor(AgnesVirtualStagingExecutor):
    def __init__(
        self,
        *,
        skills_root: str,
        codex_binary: str,
        timeout_seconds: int,
        codex_image_timeout_seconds: int = 600,
        pipeline_script: str | None = None,
    ) -> None:
        super().__init__(
            skills_root=skills_root,
            timeout_seconds=timeout_seconds,
            pipeline_script=pipeline_script,
        )
        self.codex_binary = codex_binary
        self.codex_image_timeout_seconds = codex_image_timeout_seconds

    def _build_command(
        self,
        *,
        request: AgentRequest,
        job_root: Path,
        runtime_root: Path,
        runtime_skill: Path,
        mode: str,
    ) -> list[str]:
        if mode not in {"codex-preview", "codex-auto18"}:
            raise ValueError("Modo Codex + Agnes inválido.")
        pipeline = (
            self.pipeline_script
            or runtime_root / "skills" / "codex-agnes" / "rodar.py"
        )
        if not pipeline.is_file():
            raise ValueError("O pipeline Codex + Agnes não está instalado.")
        image = self._job_file(request.payload.get("image_path"), job_root)
        return [
            sys.executable,
            str(pipeline),
            "--skill-dir",
            str(runtime_skill),
            "--output-dir",
            str(runtime_root / "output"),
            "--codex-binary",
            self.codex_binary,
            "--codex-timeout-seconds",
            str(self.codex_image_timeout_seconds),
            "--mode",
            "preview" if mode == "codex-preview" else "auto18",
            "--image",
            str(image),
        ]

    def _prepare_runtime_skill(
        self, runtime_root: Path, source: Path
    ) -> Path:
        runtime_skill = super()._prepare_runtime_skill(runtime_root, source)
        if self.pipeline_script is None:
            codex_source = self.skills_root / "codex-agnes"
            if not (codex_source / "rodar.py").is_file():
                raise ValueError("A skill Codex + Agnes não está instalada.")
            runtime_codex = runtime_root / "skills" / "codex-agnes"
            shutil.copytree(codex_source, runtime_codex, dirs_exist_ok=True)
        return runtime_skill
