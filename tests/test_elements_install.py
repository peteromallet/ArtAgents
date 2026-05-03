from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents.core.element.install import build_element_install_plan, install_element
from artagents.core.element.registry import load_default_registry
from artagents.core.executor.install import build_executor_install_plan, executor_environment_path, executor_python_path
from artagents.core.executor.registry import load_default_registry as load_executor_registry


class ElementInstallTest(unittest.TestCase):
    def element_with_dependencies(self):
        element = load_default_registry().get("effects", "text-card")
        return type(element)(
            **{
                **element.__dict__,
                "metadata": {
                    **element.metadata,
                    "dependencies": {
                        "js_packages": ["@example/element-widget@1.2.3"],
                        "python_requirements": ["example-element==4.5.6"],
                    },
                },
                "dependencies": type(element.dependencies)(
                    js_packages=("@example/element-widget@1.2.3",),
                    python_requirements=("example-element==4.5.6",),
                ),
            }
        )

    def test_element_install_plan_uses_only_element_local_paths(self) -> None:
        element = self.element_with_dependencies()
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            plan = build_element_install_plan(element, project_root=project_root)

        install_root = project_root / ".artagents" / "elements" / "effects-text-card"
        venv = install_root / "venv"
        node = install_root / "node"
        python = venv / "bin" / "python"

        self.assertEqual(plan.root, install_root)
        self.assertEqual(plan.venv_path, venv)
        self.assertEqual(plan.node_prefix, node)
        self.assertEqual(
            plan.commands,
            (
                ("uv", "venv", str(venv)),
                ("uv", "pip", "install", "--python", str(python), "example-element==4.5.6"),
                ("npm", "install", "--prefix", str(node), "@example/element-widget@1.2.3"),
            ),
        )
        self.assertNotIn("pip install example-element", "\n".join(plan.command_lines()))
        self.assertNotIn("npm install @example/element-widget", "\n".join(plan.command_lines()))

    def test_element_install_dry_run_does_not_create_dirs_or_run_package_managers(self) -> None:
        element = self.element_with_dependencies()
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            with mock.patch("artagents.core.element.install.subprocess.run") as run:
                result = install_element(element, project_root=project_root, dry_run=True)

            self.assertEqual(result.returncode, 0)
            self.assertFalse(result.plan.root.exists())
            run.assert_not_called()

    def test_element_install_apply_runs_explicit_local_commands(self) -> None:
        element = self.element_with_dependencies()
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            completed = mock.Mock(returncode=0)
            with mock.patch("artagents.core.element.install.subprocess.run", return_value=completed) as run:
                result = install_element(element, project_root=project_root, dry_run=False)

            self.assertEqual(result.returncode, 0)
            self.assertTrue(result.plan.root.is_dir())
            self.assertEqual([call.args[0] for call in run.call_args_list], list(result.plan.commands))

    def test_executor_install_paths_use_executor_cache_root_for_vibecomfy_and_moirae(self) -> None:
        registry = load_executor_registry()
        vibe_run = registry.get("external.vibecomfy.run")
        vibe_validate = registry.get("external.vibecomfy.validate")
        moirae = registry.get("external.moirae")

        self.assertEqual(executor_environment_path(vibe_run), executor_environment_path(vibe_validate))
        self.assertEqual(executor_python_path(vibe_run), executor_python_path(vibe_validate))
        self.assertTrue(str(executor_environment_path(vibe_run)).endswith(".artagents/executors/vibecomfy/venv"))
        self.assertTrue(str(executor_environment_path(moirae)).endswith(".artagents/executors/external.moirae/venv"))

        vibe_plan = build_executor_install_plan(vibe_run)
        moirae_plan = build_executor_install_plan(moirae)
        self.assertEqual(vibe_plan.environment_path, executor_environment_path(vibe_run))
        self.assertEqual(moirae_plan.environment_path, executor_environment_path(moirae))
        self.assertIn("-r", vibe_plan.commands[1])
        self.assertIn("-r", moirae_plan.commands[1])


if __name__ == "__main__":
    unittest.main()
