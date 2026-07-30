"""Roteador de intenção baseado no Codex com validação e reparo único."""

from __future__ import annotations

import json
from typing import Sequence

from codex_client import CodexClient, CodexError
from history import Message
from routing.models import RouteDecision
from routing.validator import RouteValidationError, parse_route_decision
from skills.registry import SkillRegistry


class IntentRouter:
    def __init__(self, codex: CodexClient, registry: SkillRegistry) -> None:
        self.codex = codex
        self.registry = registry

    async def decide(
        self, history: Sequence[Message], user_message: str
    ) -> RouteDecision:
        prompt = self._build_prompt(history, user_message)
        raw = await self.codex.execute_prompt(prompt)
        try:
            return parse_route_decision(raw, self.registry)
        except RouteValidationError as first_error:
            repair_prompt = (
                f"{prompt}\n\n"
                "<invalid_output>\n"
                f"{raw}\n"
                "</invalid_output>\n"
                f"Erro de validação: {first_error}\n"
                "Corrija uma única vez. Retorne somente o objeto JSON válido."
            )
            repaired = await self.codex.execute_prompt(repair_prompt)
            try:
                return parse_route_decision(repaired, self.registry)
            except RouteValidationError as exc:
                raise CodexError(
                    "O roteador não produziu uma decisão válida."
                ) from exc

    def _build_prompt(
        self, history: Sequence[Message], user_message: str
    ) -> str:
        history_value = [
            {"role": message.role, "content": message.content} for message in history
        ]
        return "\n".join(
            [
                "Você é o roteador do InemacaBot.",
                "Escolha exatamente uma ação: reply, clarify ou enqueue.",
                "Use reply para conversa e perguntas rápidas.",
                "Use enqueue apenas para tarefa demorada ou que gere artefato.",
                "Use clarify quando faltar um campo obrigatório.",
                "Nunca invente skills, filas ou campos.",
                "Retorne somente JSON, sem markdown.",
                "",
                "Skills disponíveis:",
                json.dumps(
                    self.registry.as_router_context(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "",
                "Formatos permitidos:",
                '{"action":"reply","response":"texto"}',
                '{"action":"clarify","question":"pergunta"}',
                '{"action":"enqueue","queue":"servicos","skill":"nome","payload":{}}',
                "",
                "Histórico:",
                json.dumps(history_value, ensure_ascii=False, separators=(",", ":")),
                "",
                "Mensagem atual:",
                user_message,
            ]
        )
