import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents.core.element import cli
from artagents.core.element.install import build_element_install_plan
from artagents.core.element.registry import load_default_registry


class ElementsCliTest(unittest.TestCase):
    def capture(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = cli.main(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_list_inspect_and_validate(self) -> None:
        result, stdout, stderr = self.capture(["list", "--json", "--kind", "effects"])
        self.assertEqual(result, 0, stderr)
        payload = json.loads(stdout)
        self.assertIn("text-card", {item["id"] for item in payload["elements"]})

        result, stdout, stderr = self.capture(["inspect", "effects", "text-card", "--json"])
        self.assertEqual(result, 0, stderr)
        self.assertEqual(json.loads(stdout)["id"], "text-card")

        result, stdout, stderr = self.capture(["validate", "effects", "text-card"])
        self.assertEqual(result, 0, stderr)
        self.assertIn("effects/text-card: ok", stdout)

    def test_sync_update_and_fork_use_expected_roots_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            with mock.patch.object(cli, "REPO_ROOT", project):
                result, stdout, stderr = self.capture(["sync"])
                self.assertEqual(result, 0, stderr)
                managed = project / ".artagents" / "elements" / "managed" / "effects" / "text-card"
                self.assertTrue((managed / "component.tsx").is_file())

                result, stdout, stderr = self.capture(["fork", "effects", "text-card"])
                self.assertEqual(result, 0, stderr)
                override = project / ".artagents" / "elements" / "overrides" / "effects" / "text-card"
                self.assertTrue((override / "component.tsx").is_file())

                marker = override / "USER_EDIT"
                marker.write_text("keep me", encoding="utf-8")
                result, stdout, stderr = self.capture(["update"])
                self.assertEqual(result, 0, stderr)
                self.assertTrue(marker.is_file())
                self.assertIn("skip override", stdout)

                result, stdout, stderr = self.capture(["fork", "effects", "text-card"])
                self.assertEqual(result, 2)
                self.assertIn("already exists", stderr)

    def test_install_plan_is_local_and_dry_run_by_default(self) -> None:
        registry = load_default_registry()
        element = registry.get("effects", "text-card")
        element = type(element)(
            **{
                **element.__dict__,
                "metadata": {
                    **element.metadata,
                    "dependencies": {
                        "js_packages": ["left-pad@1.3.0"],
                        "python_requirements": ["example-pkg==1.0"],
                    },
                },
                "dependencies": type(element.dependencies)(
                    js_packages=("left-pad@1.3.0",),
                    python_requirements=("example-pkg==1.0",),
                ),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_element_install_plan(element, project_root=tmp)

        lines = plan.command_lines()
        self.assertTrue(any("uv venv" in line for line in lines))
        self.assertTrue(any("uv pip install --python" in line for line in lines))
        self.assertTrue(any("npm install --prefix" in line for line in lines))
        self.assertIn(".artagents/elements/effects-text-card", str(plan.root))

    def test_install_cli_prints_dry_run_without_running_package_managers(self) -> None:
        result, stdout, stderr = self.capture(["install", "effects", "text-card"])

        self.assertEqual(result, 0, stderr)
        self.assertIn("no install needed", stdout)


if __name__ == "__main__":
    unittest.main()
