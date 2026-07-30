import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.agnes_executor import AgnesVirtualStagingExecutor
from agents.base import AgentRequest
from agents.codex_agnes_executor import CodexAgnesVirtualStagingExecutor


FAKE_SCRIPT = """\
import os
from pathlib import Path

root = Path(__file__).resolve().parents[2]
output = root / "output"
output.mkdir(parents=True, exist_ok=True)
(output / "renovation-video.mp4").write_bytes(b"video")
"""

FAKE_PIPELINE = """\
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--skill-dir")
parser.add_argument("--output-dir")
parser.add_argument("--mode")
parser.add_argument("--image")
parser.add_argument("--stages", nargs=4)
parser.add_argument("--codex-binary")
parser.add_argument("--codex-timeout-seconds")
args = parser.parse_args()
output = Path(args.output_dir)
output.mkdir(parents=True, exist_ok=True)
if args.mode == "preview":
    for index in range(1, 4):
        (output / f"stage-{index}.png").write_bytes(b"stage")
    (output / "stage-4-final-reference.png").write_bytes(b"reference")
    (output / "approval-contact-sheet.jpg").write_bytes(b"contact")
else:
    (output / "renovation-video-18s.mp4").write_bytes(b"video18")
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

    async def test_codex_agnes_preview_uses_separate_executor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "source" / "agnes"
            skill.mkdir(parents=True)
            (skill / "rodar.py").write_text(FAKE_SCRIPT, encoding="utf-8")
            codex_skill = root / "source" / "codex-agnes"
            codex_skill.mkdir(parents=True)
            (codex_skill / "rodar.py").write_text(
                FAKE_PIPELINE,
                encoding="utf-8",
            )
            job = root / "jobs" / "job_codex_preview"
            image = job / "files" / "input.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"image")
            executor = CodexAgnesVirtualStagingExecutor(
                skills_root=str(root / "source"),
                codex_binary="/usr/bin/codex",
                timeout_seconds=5,
            )
            request = AgentRequest(
                job_id="job_codex_preview",
                skill="vsvideo-codex-agnes-preview",
                payload={
                    "image_path": str(image),
                    "duration": 18,
                    "mode": "codex-preview",
                    "image_provider": "codex",
                },
                instruction="teste",
                working_directory=job,
            )

            with patch.dict(os.environ, {"AGNES_API_KEY": "test-key"}):
                result = await executor.execute(request)

            self.assertTrue(result.success)
            self.assertEqual(len(result.result["stage_files"]), 4)

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

    async def test_returns_four_files_for_approval_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "source" / "agnes"
            skill.mkdir(parents=True)
            (skill / "rodar.py").write_text(FAKE_SCRIPT, encoding="utf-8")
            (skill / "pipeline_18s.py").write_text(
                FAKE_PIPELINE,
                encoding="utf-8",
            )
            job = root / "jobs" / "job_preview"
            image = job / "files" / "input.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"image")
            executor = AgnesVirtualStagingExecutor(
                skills_root=str(root / "source"),
                timeout_seconds=5,
            )
            request = AgentRequest(
                job_id="job_preview",
                skill="vsvideo-agnes-preview",
                payload={
                    "image_path": str(image),
                    "duration": 18,
                    "mode": "preview",
                },
                instruction="teste",
                working_directory=job,
            )

            with patch.dict(os.environ, {"AGNES_API_KEY": "test-key"}):
                result = await executor.execute(request)

            self.assertTrue(result.success)
            self.assertEqual(len(result.result["files"]), 5)
            self.assertEqual(len(result.result["stage_files"]), 4)
            self.assertIn("/aprovarvideo job_preview", result.result["summary"])

    async def test_renders_eighteen_seconds_from_approved_job_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "source" / "agnes"
            skill.mkdir(parents=True)
            (skill / "rodar.py").write_text(FAKE_SCRIPT, encoding="utf-8")
            pipeline = root / "pipeline.py"
            pipeline.write_text(FAKE_PIPELINE, encoding="utf-8")
            job = root / "jobs" / "job_render"
            files = job / "files"
            files.mkdir(parents=True)
            stages = []
            for index in range(1, 5):
                stage = files / f"approved-stage-{index}.png"
                stage.write_bytes(f"stage-{index}".encode())
                stages.append(str(stage))
            executor = AgnesVirtualStagingExecutor(
                skills_root=str(root / "source"),
                timeout_seconds=5,
                pipeline_script=str(pipeline),
            )
            request = AgentRequest(
                job_id="job_render",
                skill="vsvideo-agnes-render",
                payload={
                    "stage_paths": stages,
                    "source_job_id": "job_preview",
                    "duration": 18,
                    "mode": "render18",
                },
                instruction="teste",
                working_directory=job,
            )

            with patch.dict(os.environ, {"AGNES_API_KEY": "test-key"}):
                result = await executor.execute(request)

            self.assertTrue(result.success)
            video = Path(result.result["files"][0])
            self.assertEqual(video.name, "renovation-video-18s.mp4")
            self.assertEqual(video.read_bytes(), b"video18")
            self.assertIn(job.resolve(), video.resolve().parents)
