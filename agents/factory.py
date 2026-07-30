"""Fábrica de executores permitidos pelo registro."""

from __future__ import annotations

from agents.base import AgentExecutor
from agents.agnes_executor import AgnesVirtualStagingExecutor
from agents.codex_agnes_executor import CodexAgnesVirtualStagingExecutor
from agents.codex_executor import CodexAgentExecutor
from agents.test_executor import TestQueueExecutor
from skills.registry import SkillDefinition


class AgentFactory:
    def __init__(
        self,
        *,
        codex_binary: str,
        codex_model: str | None,
        timeout_seconds: int,
        codex_image_timeout_seconds: int = 600,
        codex_agnes_timeout_seconds: int = 7200,
        test_delay_seconds: float = 10,
        vsv_skills_root: str = "/root/projetos/vsvideo-skill/skills",
    ) -> None:
        self.codex_binary = codex_binary
        self.codex_model = codex_model
        self.timeout_seconds = timeout_seconds
        self.codex_image_timeout_seconds = codex_image_timeout_seconds
        self.codex_agnes_timeout_seconds = codex_agnes_timeout_seconds
        self.test_delay_seconds = test_delay_seconds
        self.vsv_skills_root = vsv_skills_root

    def create(self, skill: SkillDefinition) -> AgentExecutor:
        if skill.executor == "test":
            return TestQueueExecutor(self.test_delay_seconds)
        if skill.executor == "codex":
            return CodexAgentExecutor(
                binary=self.codex_binary,
                model=self.codex_model,
                timeout_seconds=self.timeout_seconds,
            )
        if skill.executor == "agnes":
            return AgnesVirtualStagingExecutor(
                skills_root=self.vsv_skills_root,
                timeout_seconds=self.timeout_seconds,
            )
        if skill.executor == "codex-agnes":
            return CodexAgnesVirtualStagingExecutor(
                skills_root=self.vsv_skills_root,
                codex_binary=self.codex_binary,
                timeout_seconds=self.codex_agnes_timeout_seconds,
                codex_image_timeout_seconds=self.codex_image_timeout_seconds,
            )
        raise ValueError(f"Executor não permitido: {skill.executor}.")
