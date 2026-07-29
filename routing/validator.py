"""Validação estrita da saída não confiável do modelo."""

from __future__ import annotations

import json
from typing import Any

from queueing.models import QueueName
from routing.models import RouteAction, RouteDecision
from skills.registry import SkillRegistry


class RouteValidationError(ValueError):
    pass


def parse_route_decision(raw: str, registry: SkillRegistry) -> RouteDecision:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise RouteValidationError("A decisão não contém JSON válido.") from exc
    if not isinstance(value, dict):
        raise RouteValidationError("A decisão deve ser um objeto.")
    try:
        action = RouteAction(value.get("action"))
    except ValueError as exc:
        raise RouteValidationError("Ação de roteamento inválida.") from exc

    if action == RouteAction.REPLY:
        response = _nonempty(value.get("response"), "response")
        return RouteDecision(action=action, response=response)
    if action == RouteAction.CLARIFY:
        question = _nonempty(value.get("question"), "question")
        return RouteDecision(action=action, question=question)

    skill_name = _nonempty(value.get("skill"), "skill")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise RouteValidationError("payload deve ser um objeto.")
    try:
        queue = QueueName(value.get("queue"))
        definition = registry.validate_payload(skill_name, payload)
    except ValueError as exc:
        raise RouteValidationError(str(exc)) from exc
    if definition.queue != queue:
        raise RouteValidationError("A fila não corresponde à skill.")
    return RouteDecision(
        action=action,
        queue=queue,
        skill=skill_name,
        payload=payload,
    )


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RouteValidationError(f"{field} deve ser texto não vazio.")
    return value.strip()
