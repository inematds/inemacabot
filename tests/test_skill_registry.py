import unittest
from pathlib import Path

from queueing.models import QueueName
from skills.registry import SkillRegistry


class SkillRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        path = Path(__file__).parents[1] / "skills" / "registry.json"
        self.registry = SkillRegistry.from_file(path)

    def test_loads_one_enabled_skill_for_each_queue(self) -> None:
        queues = {skill.queue for skill in self.registry.enabled()}
        self.assertEqual(queues, set(QueueName))

    def test_validates_required_fields(self) -> None:
        definition = self.registry.validate_payload(
            "teste-fila", {"texto": "olá"}
        )
        self.assertEqual(definition.queue, QueueName.SERVICOS)
        with self.assertRaises(ValueError):
            self.registry.validate_payload("teste-fila", {})

    def test_loads_agnes_virtual_staging_skill(self) -> None:
        definition = self.registry.validate_payload(
            "vsvideo-agnes",
            {
                "image_path": "/tmp/job/image.jpg",
                "duration": 18,
                "mode": "auto18",
            },
        )
        self.assertEqual(definition.queue, QueueName.VIDEOS)
        self.assertEqual(definition.executor, "agnes")

    def test_loads_codex_agnes_virtual_staging_skill(self) -> None:
        definition = self.registry.validate_payload(
            "vsvideo-codex-agnes-preview",
            {
                "image_path": "/tmp/job/image.jpg",
                "duration": 18,
                "mode": "codex-preview",
                "image_provider": "codex",
            },
        )
        self.assertEqual(definition.queue, QueueName.VIDEOS)
        self.assertEqual(definition.executor, "codex-agnes")


if __name__ == "__main__":
    unittest.main()
