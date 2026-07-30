import json
import tempfile
import unittest
from pathlib import Path

from queueing.models import QueueName
from routing.models import RouteAction
from routing.validator import RouteValidationError, parse_route_decision
from skills.registry import SkillRegistry


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.temporary.name) / "skills.json"
        self.registry_path.write_text(
            json.dumps(
                {
                    "pesquisa": {
                        "queue": "servicos",
                        "description": "Pesquisa",
                        "enabled": True,
                        "requiredFields": ["tema"],
                        "executor": "codex",
                        "instruction": "Pesquise.",
                    }
                }
            ),
            encoding="utf-8",
        )
        self.registry = SkillRegistry.from_file(self.registry_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_reply(self) -> None:
        decision = parse_route_decision(
            '{"action":"reply","response":"Olá"}', self.registry
        )
        self.assertEqual(decision.action, RouteAction.REPLY)
        self.assertEqual(decision.response, "Olá")

    def test_accepts_valid_job(self) -> None:
        decision = parse_route_decision(
            '{"action":"enqueue","queue":"servicos","skill":"pesquisa",'
            '"payload":{"tema":"filas"}}',
            self.registry,
        )
        self.assertEqual(decision.queue, QueueName.SERVICOS)
        self.assertEqual(decision.payload["tema"], "filas")

    def test_rejects_unknown_skill(self) -> None:
        with self.assertRaises(RouteValidationError):
            parse_route_decision(
                '{"action":"enqueue","queue":"servicos","skill":"inventada",'
                '"payload":{"tema":"x"}}',
                self.registry,
            )

    def test_rejects_missing_required_field(self) -> None:
        with self.assertRaises(RouteValidationError):
            parse_route_decision(
                '{"action":"enqueue","queue":"servicos","skill":"pesquisa",'
                '"payload":{}}',
                self.registry,
            )


if __name__ == "__main__":
    unittest.main()
