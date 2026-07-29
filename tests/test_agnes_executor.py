import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.agnes_executor import AgnesVirtualStagingExecutor
from agents.base import AgentRequest


FAKE_SCRIPT = """\
import os
from pathlib import Path

root = Path(__file__).resolve().parents[2]
output = root / "output"
output.mkdir(parents=True, exist_ok=True)
(output / "renovation-video.mp4").write_bytes(b"video")
"""


class AgnesVirtualStagingExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_copies_skill_and_returns_video_inside_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "source" / "agnes"
            skill.mkdir(parents=True)
            (skill / "rodar.py").write_text(FAKE_SCRIPT, encoding="utf-8")
            job = root / "jobs" / "job_1"
            image = job / "files" / "input.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"image")
            executor = AgnesVirtualStagingExecutor(
                skills_root=str(root / "source"),
                timeout_seconds=5,
            )
            request = AgentRequest(
                job_id="job_1",
                skill="vsvideo-agnes",
                payload={"image_path": str(image)},
                instruction="teste",
                working_directory=job,
            )

            with patch.dict(os.environ, {"AGNES_API_KEY": "test-key"}):
                result = await executor.execute(request)

            self.assertTrue(result.success)
            video = Path(result.result["files"][0])
            self.assertEqual(video.read_bytes(), b"video")
            self.assertIn(job.resolve(), video.resolve().parents)

    async def test_rejects_image_outside_job_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.jpg"
            outside.write_bytes(b"image")
            job = root / "job"
            job.mkdir()
            executor = AgnesVirtualStagingExecutor(
                skills_root=str(root / "source"),
                timeout_seconds=5,
            )
            result = await executor.execute(
                AgentRequest(
                    job_id="job",
                    skill="vsvideo-agnes",
                    payload={"image_path": str(outside)},
                    instruction="teste",
                    working_directory=job,
                )
            )
            self.assertFalse(result.success)
