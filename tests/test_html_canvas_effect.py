import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from astrid.core.element.schema import load_element_definition
from astrid.core.executor import cli as executors_cli
from astrid.core.executor.registry import load_default_registry as load_executor_registry
from astrid.packs.builtin.executors.html_canvas_effect.run import main, scaffold


class HtmlCanvasEffectExecutorTest(unittest.TestCase):
    def test_executor_is_discoverable(self) -> None:
        registry = load_executor_registry()
        executor = registry.get("builtin.html_canvas_effect")

        self.assertEqual(executor.metadata["runtime_module"], "astrid.packs.builtin.executors.html_canvas_effect.run")
        self.assertIn("HtmlInCanvas", executor.description)

    def test_scaffold_writes_local_effect_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            report_path = project / "runs" / "effect" / "report.json"

            report = scaffold(
                effect_id="glass-product-card",
                label="Glass Product Card",
                description="A test effect.",
                project_root=project,
                out_path=report_path,
            )

            element_root = project / "astrid" / "packs" / "local" / "elements" / "effects" / "glass-product-card"
            self.assertEqual(Path(report["element_root"]), element_root)
            self.assertTrue((element_root / "component.tsx").is_file())
            self.assertTrue((element_root / "element.yaml").is_file())
            self.assertTrue(report_path.is_file())

            component = (element_root / "component.tsx").read_text(encoding="utf-8")
            self.assertIn("HtmlInCanvas", component)
            self.assertIn("drawElementImage", component)

            manifest = json.loads((element_root / "element.yaml").read_text(encoding="utf-8"))
            self.assertEqual(manifest["id"], "glass-product-card")
            self.assertEqual(manifest["pack_id"], "local")
            self.assertTrue(manifest["metadata"]["render_requirements"]["uses_html_in_canvas"])
            self.assertEqual(manifest["metadata"]["render_requirements"]["final_renderer"], "builtin.render")

            element = load_element_definition(element_root, kind="effects", source="pack:local", editable=True, priority=10)
            self.assertEqual(element.id, "glass-product-card")
            self.assertEqual(element.metadata["pack_id"], "local")

    def test_scaffold_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            report_path = project / "report.json"
            scaffold(effect_id="canvas-card", label=None, description=None, project_root=project, out_path=report_path)

            with self.assertRaisesRegex(FileExistsError, "already exists"):
                scaffold(effect_id="canvas-card", label=None, description=None, project_root=project, out_path=report_path)

            scaffold(effect_id="canvas-card", label=None, description=None, project_root=project, out_path=report_path, force=True)

    def test_main_validates_effect_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(["--effect-id", "Bad_ID", "--project-root", tmp, "--out", str(Path(tmp) / "report.json")])

            self.assertEqual(code, 1)
            self.assertIn("kebab-case", stderr.getvalue())

    def test_canonical_cli_dry_run_uses_executor_runtime(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = executors_cli.main(
                [
                    "run",
                    "builtin.html_canvas_effect",
                    "--input",
                    "effect_id=glass-product-card",
                    "--out",
                    "runs/html-canvas-effect",
                    "--dry-run",
                ]
            )

        self.assertEqual(result, 0, stderr.getvalue())
        self.assertIn("astrid.packs.builtin.executors.html_canvas_effect.run", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
