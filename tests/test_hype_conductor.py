import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents import pipeline
from artagents.conductors import ConductorRunRequest, load_default_registry, run_conductor


class HypeConductorTest(unittest.TestCase):
    def test_builtin_hype_is_registered_with_step_order_child_performers(self) -> None:
        conductor = load_default_registry().get("builtin.hype")

        self.assertEqual(conductor.kind, "built_in")
        self.assertEqual(conductor.runtime.kind, "python")
        self.assertEqual(conductor.child_performers, tuple(f"builtin.{name}" for name in pipeline.STEP_ORDER))

    def test_hype_dry_run_plans_commands_without_executing_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brief = root / "brief.txt"
            brief.write_text("make a short edit", encoding="utf-8")
            request = ConductorRunRequest(
                "builtin.hype",
                out=root / "out",
                brief=brief,
                conductor_args=("--target-duration", "12", "--from", "cut", "--skip", "render"),
                dry_run=True,
            )
            registry = load_default_registry()

            with (
                mock.patch.object(pipeline, "pool_main", side_effect=AssertionError("pool_main should not run")),
                mock.patch("subprocess.Popen", side_effect=AssertionError("subprocess should not start")),
                mock.patch("subprocess.run", side_effect=AssertionError("subprocess should not run")),
                mock.patch.object(pipeline.asset_cache, "fetch", side_effect=AssertionError("prefetch should not run")),
            ):
                result = run_conductor(request, registry)

        self.assertTrue(result.dry_run)
        self.assertIsNone(result.returncode)
        self.assertTrue(result.planned_commands)
        self.assertIsNotNone(result.plan)
        self.assertEqual([step.command for step in result.plan.steps], list(result.planned_commands))
        planned_text = "\n".join(" ".join(command) for command in result.planned_commands)
        self.assertIn("cut.py", planned_text)
        self.assertNotIn("render_remotion.py", planned_text)
        self.assertNotIn("arrange.py", planned_text)

    def test_hype_dry_run_requires_generic_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brief = root / "brief.txt"
            brief.write_text("make a short edit", encoding="utf-8")

            with self.assertRaisesRegex(Exception, "--out is required for builtin.hype dry-run"):
                run_conductor(
                    ConductorRunRequest(
                        "builtin.hype",
                        brief=brief,
                        conductor_args=("--target-duration", "12"),
                        dry_run=True,
                    )
                )

    def test_hype_dry_run_applies_render_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brief = root / "brief.txt"
            audio = root / "audio.wav"
            brief.write_text("make a short edit", encoding="utf-8")
            audio.write_bytes(b"not a real wav; dry-run only")

            result = run_conductor(
                ConductorRunRequest(
                    "builtin.hype",
                    out=root / "out",
                    brief=brief,
                    conductor_args=("--audio", str(audio), "--target-duration", "12", "--render", "--from", "render"),
                    dry_run=True,
                )
            )

        planned_text = "\n".join(" ".join(command) for command in result.planned_commands)
        self.assertEqual([step.command for step in result.plan.steps], list(result.planned_commands))
        self.assertIn("render_remotion.py", planned_text)
        self.assertIn("validate.py", planned_text)
        self.assertNotIn("cut.py", planned_text)

    def test_hype_real_execution_uses_legacy_pipeline_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brief = root / "brief.txt"
            brief.write_text("make a short edit", encoding="utf-8")

            with mock.patch.object(pipeline, "main", return_value=0) as legacy_main:
                result = run_conductor(
                    ConductorRunRequest(
                        "builtin.hype",
                        out=root / "out",
                        brief=brief,
                        conductor_args=("--target-duration", "12"),
                    )
                )

        self.assertEqual(result.returncode, 0)
        legacy_main.assert_called_once()
        argv = legacy_main.call_args.args[0]
        self.assertIn("--out", argv)
        self.assertIn("--brief", argv)
        self.assertIn("--target-duration", argv)


if __name__ == "__main__":
    unittest.main()
