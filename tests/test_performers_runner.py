import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents import pipeline
from artagents.performers.install import performer_python_path
from artagents.performers.registry import PerformerRegistry
from artagents.performers.runner import PerformerRunRequest, PerformerRunnerError, build_legacy_context, build_performer_command, run_performer


class PerformerRunnerTest(unittest.TestCase):
    def test_builtin_run_uses_legacy_step_builder_with_full_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brief = root / "brief.txt"
            brief.write_text("make a short edit", encoding="utf-8")
            request = PerformerRunRequest("builtin.render", out=root / "run", brief=brief)

            context = build_legacy_context(request)
            required_fields = {
                "audio",
                "video",
                "out",
                "brief",
                "brief_out",
                "brief_copy",
                "skip",
                "asset_pairs",
                "primary_asset",
                "theme",
                "theme_explicit",
                "source_slug",
                "brief_slug",
                "env_file",
                "extra_args",
                "target_duration",
                "python_exec",
                "render",
                "verbose",
                "no_prefetch",
                "keep_downloads",
                "cache_dir",
                "drift",
            }
            self.assertTrue(all(hasattr(context, name) for name in required_fields))

            with mock.patch.object(pipeline, "run_step", return_value=0) as run_step:
                result = run_performer(request)

        self.assertEqual(result.returncode, 0)
        self.assertIn("render_remotion.py", result.command[1])
        run_step.assert_called_once()

    def test_external_moirae_dry_run_preserves_python_input_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screenplay = root / "screenplay.md"
            screenplay.write_text("INT. TERMINAL - DAY", encoding="utf-8")
            python_exec = root / "custom-python"

            result = run_performer(
                PerformerRunRequest(
                    "external.moirae",
                    out=root / "out",
                    inputs={"screenplay": screenplay, "python_exec": python_exec},
                    dry_run=True,
                )
            )

        self.assertEqual(result.returncode, None)
        self.assertEqual(result.command[:3], (str(python_exec), "-m", "moirae"))
        self.assertIn(str(screenplay), result.command)
        self.assertTrue(result.command[-1].endswith("/out/video"))

    def test_external_run_uses_installed_performer_python_when_available(self) -> None:
        fake = self.external_python_node("external.fake_installed")
        registry = PerformerRegistry([fake])
        performer = registry.get("external.fake_installed")
        python_path = performer_python_path(performer)
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("# fake python\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, python_path.parents[2], True)

        result = run_performer(PerformerRunRequest(performer.id, out="runs/performer-test", dry_run=True), registry)

        self.assertEqual(result.command[:2], (str(python_path), "--version"))

    def test_external_run_preserves_explicit_request_python_override(self) -> None:
        fake = self.external_python_node("external.fake_override")
        registry = PerformerRegistry([fake])
        performer = registry.get("external.fake_override")
        python_path = performer_python_path(performer)
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("# fake python\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, python_path.parents[2], True)

        result = run_performer(
            PerformerRunRequest(performer.id, out="runs/performer-test", dry_run=True, python_exec="/tmp/explicit-python"),
            registry,
        )

        self.assertEqual(result.command[:2], ("/tmp/explicit-python", "--version"))

    def test_external_run_without_env_or_override_fails_actionably(self) -> None:
        fake = self.external_python_node("external.fake_missing_env")
        registry = PerformerRegistry([fake])

        with self.assertRaisesRegex(PerformerRunnerError, r"pipeline.py performers install external\.fake_missing_env"):
            run_performer(PerformerRunRequest("external.fake_missing_env", out="runs/performer-test", dry_run=True), registry)

    def test_missing_required_input_fails_before_command_building(self) -> None:
        with self.assertRaisesRegex(PerformerRunnerError, "screenplay"):
            build_performer_command(PerformerRunRequest("external.moirae", out="runs/performer-test", dry_run=True))

    def test_binary_requirements_are_gated_by_request_flag(self) -> None:
        fake = self.external_python_node(
            "external.fake_binary",
            isolation={"mode": "subprocess", "binaries": ["definitely-not-an-artagents-binary"]},
        )
        registry = PerformerRegistry([fake])

        unchecked = run_performer(
            PerformerRunRequest(
                "external.fake_binary",
                out="runs/performer-test",
                dry_run=True,
                python_exec="/tmp/explicit-python",
            ),
            registry,
        )
        checked = run_performer(
            PerformerRunRequest(
                "external.fake_binary",
                out="runs/performer-test",
                dry_run=True,
                check_binaries=True,
                python_exec="/tmp/explicit-python",
            ),
            registry,
        )

        self.assertEqual(unchecked.missing_binaries, ())
        self.assertEqual(checked.missing_binaries, ("definitely-not-an-artagents-binary",))

    def external_python_node(self, performer_id: str, *, isolation: dict | None = None) -> dict:
        return {
            "id": performer_id,
            "name": "Fake Python",
            "kind": "external",
            "version": "1",
            "command": {"argv": ["{python_exec}", "--version"]},
            "isolation": isolation or {"mode": "subprocess"},
        }


if __name__ == "__main__":
    unittest.main()
