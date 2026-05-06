from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from artagents import doctor, setup_cli
from artagents.core.element.registry import load_default_registry as load_element_registry
from artagents.structure import TOP_LEVEL_ARTAGENTS_DIRS, validate_repo_structure


class DoctorSetupTest(unittest.TestCase):
    def capture(self, fn, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = fn(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_doctor_text_and_json_reports_required_checks(self) -> None:
        result, stdout, stderr = self.capture(doctor.main, [])

        self.assertEqual(result, 0, stderr)
        self.assertIn("ArtAgents doctor", stdout)
        self.assertIn("[ok] python:", stdout)
        self.assertIn("[ok] executor registry:", stdout)
        self.assertIn("[ok] orchestrator registry:", stdout)
        self.assertIn("[ok] element registry:", stdout)
        self.assertIn("[ok] repo structure:", stdout)
        self.assertIn("[ok] vibecomfy metadata:", stdout)
        self.assertIn("[ok] remotion config:", stdout)
        self.assertIn("[ok] timeline catalog:", stdout)

        result, stdout, stderr = self.capture(doctor.main, ["--json"])
        self.assertEqual(result, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("repo structure", {item["name"] for item in payload["checks"]})
        self.assertIn("vibecomfy metadata", {item["name"] for item in payload["checks"]})

    def test_doctor_required_check_failure_returns_nonzero(self) -> None:
        with mock.patch.object(doctor, "load_executor_registry", side_effect=RuntimeError("registry exploded")):
            result, stdout, stderr = self.capture(doctor.main, [])

        self.assertEqual(result, 1)
        self.assertEqual(stderr, "")
        self.assertIn("[fail] executor registry: registry exploded", stdout)

    def test_doctor_optional_binaries_warn_by_default_and_can_be_strict(self) -> None:
        with mock.patch.object(doctor.shutil, "which", return_value=None):
            result, stdout, stderr = self.capture(doctor.main, [])
            strict_result, strict_stdout, strict_stderr = self.capture(doctor.main, ["--strict-optional"])

        self.assertEqual(result, 0, stderr)
        self.assertIn("[warn] optional binary ffmpeg: not found on PATH", stdout)
        self.assertEqual(strict_result, 1, strict_stderr)
        self.assertIn("[warn] optional binary ffmpeg: not found on PATH", strict_stdout)

    def test_setup_dry_run_does_not_mutate_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            with mock.patch.object(setup_cli, "REPO_ROOT", project_root):
                result, stdout, stderr = self.capture(setup_cli.main, [])

            self.assertEqual(result, 0, stderr)
            self.assertIn("ArtAgents setup", stdout)
            self.assertIn("dry-run: pass --apply", stdout)
            self.assertNotIn("elements sync", stdout)
            self.assertFalse((project_root / ".artagents" / "elements" / "managed").exists())
            self.assertFalse((project_root / "artagents" / "packs" / "local").exists())

    def test_setup_json_dry_run_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            with mock.patch.object(setup_cli, "REPO_ROOT", project_root):
                result, stdout, stderr = self.capture(setup_cli.main, ["--json"])

        self.assertEqual(result, 0, stderr)
        payload = json.loads(stdout)
        self.assertFalse(payload["applied"])
        self.assertIn("dry-run", {step["status"] for step in payload["steps"]})

    def test_setup_apply_delegates_to_install_helpers(self) -> None:
        registry = load_element_registry()
        element = registry.get("effects", "text-card")
        fake_registry = SimpleNamespace(list=lambda: (element,))
        fake_plan = SimpleNamespace(noop_reason="no dependencies declared", command_lines=lambda: ())
        fake_result = SimpleNamespace(plan=fake_plan)

        with mock.patch.object(
            setup_cli, "load_element_registry", return_value=fake_registry
        ) as load_registry, mock.patch.object(setup_cli, "install_element", return_value=fake_result) as install:
            result, stdout, stderr = self.capture(setup_cli.main, ["--apply"])

        self.assertEqual(result, 0, stderr)
        load_registry.assert_called_once_with(project_root=setup_cli.REPO_ROOT)
        install.assert_called_once_with(element, project_root=setup_cli.REPO_ROOT, dry_run=False)
        self.assertNotIn("elements sync", stdout)
        self.assertIn("[skipped] elements install: effects/text-card: no dependencies declared", stdout)

    def test_top_level_dirs_includes_verify_and_orchestrate(self) -> None:
        self.assertIn("verify", TOP_LEVEL_ARTAGENTS_DIRS)
        self.assertIn("orchestrate", TOP_LEVEL_ARTAGENTS_DIRS)

    def test_repo_structure_guard_rejects_legacy_and_misplaced_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artagents" / "conductors").mkdir(parents=True)
            (root / "artagents" / "tools" / "reigh-data").mkdir(parents=True)
            external_pack_dir = root / "artagents" / "packs" / "external"
            external_pack_dir.mkdir(parents=True)
            (external_pack_dir / "pack.yaml").write_text("id: external\n", encoding="utf-8")
            mixed_orchestrator = external_pack_dir / "vibecomfy"
            mixed_orchestrator.mkdir(parents=True)
            (mixed_orchestrator / "STAGE.md").write_text("# stage\n", encoding="utf-8")
            (mixed_orchestrator / "run.py").write_text("", encoding="utf-8")
            (mixed_orchestrator / "orchestrator.yaml").write_text(
                "\n".join(
                    [
                        "id: external.vibecomfy",
                        "name: VibeComfy",
                        "kind: external",
                        "version: '1.0'",
                        "runtime:",
                        "  kind: command",
                        "  command:",
                        "    argv: [\"echo\", \"vibe\"]",
                    ]
                ),
                encoding="utf-8",
            )
            (mixed_orchestrator / "executor.yaml").write_text(
                "\n".join(
                    [
                        "id: external.vibecomfy.run",
                        "name: VibeComfy Run",
                        "kind: external",
                        "version: '1.0'",
                        "command:",
                        "  argv: [\"echo\", \"run\"]",
                    ]
                ),
                encoding="utf-8",
            )
            misplaced_executor = external_pack_dir / "render"
            misplaced_executor.mkdir(parents=True)
            (misplaced_executor / "STAGE.md").write_text("# stage\n", encoding="utf-8")
            (misplaced_executor / "run.py").write_text("", encoding="utf-8")
            (misplaced_executor / "executor.yaml").write_text(
                "\n".join(
                    [
                        "id: builtin.render",
                        "name: Render",
                        "kind: built_in",
                        "version: '1.0'",
                        "command:",
                        "  argv: [\"echo\", \"render\"]",
                    ]
                ),
                encoding="utf-8",
            )

            report = validate_repo_structure(root)

        self.assertFalse(report.ok)
        detail = "\n".join(report.errors)
        self.assertIn("legacy public package must not exist: artagents/conductors", detail)
        self.assertIn("top-level artagents directory is not a canonical concept: artagents/tools", detail)
        self.assertIn(
            "orchestrator folder contains executor metadata: artagents/packs/external/vibecomfy",
            detail,
        )
        self.assertIn("executor 'builtin.render' must live in pack 'builtin' but was found in pack 'external'", detail)


if __name__ == "__main__":
    unittest.main()
