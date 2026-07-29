"""Carregamento seguro do registro central de skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from queueing.models import QueueName


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    name: str
    queue: QueueName
    description: str
    enabled: bool
    required_fields: tuple[str, ...]
    executor: str
    instruction: str


class SkillRegistry:
    ALLOWED_EXECUTORS = {"test", "codex", "agnes"}

    def __init__(self, definitions: dict[str, SkillDefinition]) -> None:
        self._definitions = definitions

    @classmethod
    def from_file(cls, path: str | Path) -> "SkillRegistry":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Não foi possível carregar o registro de skills.") from exc
        if not isinstance(raw, dict) or not raw:
            raise ValueError("O registro de skills deve ser um objeto não vazio.")
        definitions: dict[str, SkillDefinition] = {}
        for name, value in raw.items():
            definitions[name] = cls._parse(name, value)
        return cls(definitions)

    @classmethod
    def _parse(cls, name: str, value: Any) -> SkillDefinition:
        if not isinstance(name, str) or not name.strip() or not isinstance(value, dict):
            raise ValueError("Definição de skill inválida.")
        required = value.get("requiredFields")
        if (
            not isinstance(required, list)
            or any(not isinstance(field, str) or not field for field in required)
            or len(required) != len(set(required))
        ):
            raise ValueError(f"requiredFields inválido na skill {name!r}.")
        executor = value.get("executor")
        if executor not in cls.ALLOWED_EXECUTORS:
            raise ValueError(f"Executor inválido na skill {name!r}.")
        description = value.get("description")
        instruction = value.get("instruction")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Descrição inválida na skill {name!r}.")
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError(f"Instrução inválida na skill {name!r}.")
        return SkillDefinition(
            name=name,
            queue=QueueName(value.get("queue")),
            description=description.strip(),
            enabled=value.get("enabled") is True,
            required_fields=tuple(required),
            executor=executor,
            instruction=instruction.strip(),
        )

    def get(self, name: str, *, require_enabled: bool = True) -> SkillDefinition:
        definition = self._definitions.get(name)
        if definition is None:
            raise ValueError(f"Skill inexistente: {name}.")
        if require_enabled and not definition.enabled:
            raise ValueError(f"Skill desabilitada: {name}.")
        return definition

    def enabled(self) -> tuple[SkillDefinition, ...]:
        return tuple(
            definition
            for definition in self._definitions.values()
            if definition.enabled
        )

    def validate_payload(
        self, skill_name: str, payload: dict[str, Any]
    ) -> SkillDefinition:
        definition = self.get(skill_name)
        if not isinstance(payload, dict):
            raise ValueError("O payload deve ser um objeto.")
        encoded = json.dumps(payload, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 64 * 1024:
            raise ValueError("O payload ultrapassa 64 KiB.")
        if _json_depth(payload) > 8:
            raise ValueError("O payload excede a profundidade permitida.")
        missing = [
            field
            for field in definition.required_fields
            if field not in payload
            or payload[field] is None
            or (isinstance(payload[field], str) and not payload[field].strip())
        ]
        if missing:
            raise ValueError(
                "Campos obrigatórios ausentes: " + ", ".join(sorted(missing))
            )
        return definition

    def as_router_context(self) -> list[dict[str, Any]]:
        return [
            {
                "name": definition.name,
                "queue": definition.queue.value,
                "description": definition.description,
                "requiredFields": list(definition.required_fields),
            }
            for definition in self.enabled()
        ]


def _json_depth(value: Any, current: int = 0) -> int:
    if isinstance(value, dict):
        return max(
            ([_json_depth(item, current + 1) for item in value.values()] or [current])
        )
    if isinstance(value, list):
        return max(
            ([_json_depth(item, current + 1) for item in value] or [current])
        )
    return current
