import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from artagents.performers import cli
from artagents.performers.install import build_performer_install_plan, performer_environment_path, performer_python_path
from artagents.performers.registry import load_default_registry


class NodeCliTest(unittest.TestCase):
    def invoke(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = cli.main(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_list_json_includes_builtins_and_moirae(self) -> None:
        result, stdout, stderr = self.invoke(["list", "--json"])

        self.assertEqual(result, 0, stderr)
        ids = {performer["id"] for performer in json.loads(stdout)["performers"]}
        self.assertIn("builtin.render", ids)
        self.assertIn("external.moirae", ids)

    def test_list_kind_filter_outputs_external_node(self) -> None:
        result, stdout, stderr = self.invoke(["list", "--kind", "external"])

        self.assertEqual(result, 0, stderr)
        self.assertIn("external.moirae", stdout)
        self.assertNotIn("builtin.render", stdout)

    def test_inspect_json_outputs_performer_metadata(self) -> None:
        result, stdout, stderr = self.invoke(["inspect", "external.moirae", "--json"])

        self.assertEqual(result, 0, stderr)
        performer = json.loads(stdout)
        self.assertEqual(performer["id"], "external.moirae")
        self.assertEqual(performer["outputs"][0]["placeholder"], "output")

    def test_inspect_json_outputs_vibecomfy_metadata(self) -> None:
        result, stdout, stderr = self.invoke(["inspect", "external.vibecomfy.run", "--json"])

        self.assertEqual(result, 0, stderr)
        performer = json.loads(stdout)
        self.assertEqual(performer["id"], "external.vibecomfy.run")
        self.assertEqual(performer["metadata"]["package_id"], "vibecomfy")
        self.assertEqual(performer["metadata"]["folder_id"], "vibecomfy")
        self.assertTrue(performer["metadata"]["requirements_file"].endswith("artagents/performers/curated/vibecomfy/requirements.txt"))
        self.assertEqual(performer["command"]["argv"], ["{python_exec}", "-m", "vibecomfy.cli", "run", "{workflow}"])

    def test_validate_outputs_ok(self) -> None:
        result, stdout, stderr = self.invoke(["validate", "external.moirae"])

        self.assertEqual(result, 0, stderr)
        self.assertIn("external.moirae: ok", stdout)

    def test_run_external_dry_run_expands_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screenplay = root / "screenplay.md"
            screenplay.write_text("EXT. PERFORMER TEST - DAY", encoding="utf-8")
            python_exec = root / "python"

            result, stdout, stderr = self.invoke(
                [
                    "run",
                    "external.moirae",
                    "--out",
                    str(root / "out"),
                    "--input",
                    f"screenplay={screenplay}",
                    "--input",
                    f"python_exec={python_exec}",
                    "--dry-run",
                ]
            )

        self.assertEqual(result, 0, stderr)
        self.assertIn("-m moirae", stdout)
        self.assertIn(str(python_exec), stdout)
        self.assertIn(str(screenplay), stdout)
        self.assertIn("/out/video", stdout)

    def test_run_vibecomfy_validate_dry_run_expands_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / "workflow.json"
            workflow.write_text("{}", encoding="utf-8")
            python_exec = root / "python"

            result, stdout, stderr = self.invoke(
                [
                    "run",
                    "external.vibecomfy.validate",
                    "--out",
                    str(root / "out"),
                    "--input",
                    f"workflow={workflow}",
                    "--input",
                    f"python_exec={python_exec}",
                    "--dry-run",
                ]
            )

        self.assertEqual(result, 0, stderr)
        self.assertIn("-m vibecomfy.cli validate", stdout)
        self.assertIn(str(python_exec), stdout)
        self.assertIn(str(workflow), stdout)

    def test_run_external_without_env_or_override_names_install_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screenplay = root / "screenplay.md"
            screenplay.write_text("EXT. PERFORMER TEST - DAY", encoding="utf-8")

            result, stdout, stderr = self.invoke(
                [
                    "run",
                    "external.moirae",
                    "--out",
                    str(root / "out"),
                    "--input",
                    f"screenplay={screenplay}",
                    "--dry-run",
                ]
            )

        self.assertEqual(result, 2)
        self.assertEqual(stdout, "")
        self.assertIn("pipeline.py performers install external.moirae", stderr)

    def test_install_external_dry_run_prints_uv_plan_without_creating_env(self) -> None:
        result, stdout, stderr = self.invoke(["install", "external.moirae", "--dry-run"])

        self.assertEqual(result, 0, stderr)
        registry = load_default_registry()
        performer = registry.get("external.moirae")
        env_path = performer_environment_path(performer)
        python_path = performer_python_path(performer)
        self.assertIn(f"env: {env_path}", stdout)
        self.assertIn(f"python: {python_path}", stdout)
        self.assertIn(f"uv venv {env_path}", stdout)
        self.assertIn("uv pip install", stdout)
        self.assertIn(f"--python {python_path}", stdout)
        self.assertIn(f"-r {performer.metadata['requirements_file']}", stdout)
        self.assertNotIn(" uv pip install --python " + str(python_path) + " moirae", stdout)
        self.assertFalse(env_path.exists())

    def test_install_builtin_is_host_env_noop(self) -> None:
        result, stdout, stderr = self.invoke(["install", "builtin.render", "--dry-run"])

        self.assertEqual(result, 0, stderr)
        self.assertIn("builtin.render: no install needed", stdout)
        self.assertIn("host Python environment", stdout)
        self.assertNotIn("uv venv", stdout)

    def test_install_helpers_use_deterministic_performer_env_contract(self) -> None:
        performer = load_default_registry().get("external.moirae")
        plan = build_performer_install_plan(performer)

        self.assertEqual(plan.environment_path, performer_environment_path(performer))
        self.assertEqual(plan.python_path, performer_python_path(performer))
        self.assertTrue(str(plan.environment_path).endswith(".artagents/performers/external.moirae/venv"))
        self.assertIn(str(plan.python_path), plan.commands[1])

    def test_vibecomfy_install_helpers_share_package_env_and_preserve_moirae_env(self) -> None:
        registry = load_default_registry()
        run = registry.get("external.vibecomfy.run")
        validate = registry.get("external.vibecomfy.validate")
        moirae = registry.get("external.moirae")
        run_plan = build_performer_install_plan(run)

        self.assertEqual(performer_environment_path(run), performer_environment_path(validate))
        self.assertEqual(performer_python_path(run), performer_python_path(validate))
        self.assertTrue(str(performer_environment_path(run)).endswith(".artagents/performers/vibecomfy/venv"))
        self.assertTrue(str(performer_environment_path(moirae)).endswith(".artagents/performers/external.moirae/venv"))
        self.assertEqual(run_plan.environment_path, performer_environment_path(run))
        self.assertIn("-r", run_plan.commands[1])
        self.assertIn(run.metadata["requirements_file"], run_plan.commands[1])


if __name__ == "__main__":
    unittest.main()
