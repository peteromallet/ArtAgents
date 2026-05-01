import json
import sys
import ast
import tempfile
import unittest
from dataclasses import asdict, is_dataclass
from pathlib import Path

from artagents.conductors import (
    ConductorPlan,
    ConductorPlanStep,
    ConductorRegistry,
    ConductorRunRequest,
    ConductorRunResult,
    ConductorRunnerError,
    Output,
    Port,
    build_conductor_command,
    run_conductor,
)


def conductor_manifest(conductor_id: str, runtime: dict, *, inputs: list[Port] | None = None, outputs: list[Output] | None = None) -> dict:
    return {
        "id": conductor_id,
        "name": conductor_id.replace(".", " ").title(),
        "kind": "external",
        "version": "1.0",
        "runtime": runtime,
        "inputs": [_plain(item) for item in inputs or []],
        "outputs": [_plain(item) for item in outputs or []],
        "cache": {"mode": "none"},
    }


def _plain(value):
    if is_dataclass(value):
        return {key: item for key, item in asdict(value).items() if item is not None and item != ""}
    return value


class ConductorRunnerTest(unittest.TestCase):
    def test_command_runtime_dry_run_expands_placeholders_and_passthrough_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brief = root / "brief.txt"
            brief.write_text("make a short edit", encoding="utf-8")
            registry = ConductorRegistry(
                [
                    conductor_manifest(
                        "external.command",
                        {
                            "kind": "command",
                            "command": {
                                "argv": [
                                    "{python_exec}",
                                    "-m",
                                    "example",
                                    "--brief",
                                    "{brief}",
                                    "--manifest",
                                    "{manifest_out}",
                                    "{conductor_args}",
                                ],
                                "cwd": "{out}",
                                "env": {"ARTAGENTS_VERBOSE": "{verbose}"},
                            },
                        },
                        inputs=[Port("brief", "file")],
                        outputs=[Output("manifest", "file", placeholder="manifest_out")],
                    )
                ]
            )

            result = run_conductor(
                ConductorRunRequest(
                    "external.command",
                    out=root / "out",
                    brief=brief,
                    conductor_args=("--flag", "value"),
                    dry_run=True,
                    python_exec="/tmp/python",
                    verbose=True,
                ),
                registry,
            )

        self.assertIsNone(result.returncode)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.command[0], "/tmp/python")
        self.assertEqual(Path(result.command[4]).resolve(), brief.resolve())
        self.assertTrue(result.command[-3].endswith("/out/manifest"))
        self.assertEqual(result.command[-2:], ("--flag", "value"))
        self.assertEqual(result.planned_commands, (result.command,))
        self.assertIsNotNone(result.plan)
        self.assertEqual(result.plan.steps[0].command, result.command)
        self.assertEqual(result.to_dict()["plan"]["steps"][0]["command"], list(result.command))
        self.assertTrue(result.cwd.endswith("/out"))
        self.assertEqual(result.env["ARTAGENTS_VERBOSE"], "true")

    def test_command_runtime_dry_run_can_omit_unused_out(self) -> None:
        registry = ConductorRegistry(
            [
                conductor_manifest(
                    "external.no_out_dry_run",
                    {"kind": "command", "command": {"argv": ["echo", "{topic}", "{conductor_args}"]}},
                    inputs=[Port("topic", "string")],
                )
            ]
        )

        result = run_conductor(
            ConductorRunRequest(
                "external.no_out_dry_run",
                inputs={"topic": "launch"},
                conductor_args=("now",),
                dry_run=True,
            ),
            registry,
        )

        self.assertEqual(result.planned_commands, (("echo", "launch", "now"),))
        self.assertEqual(result.plan.steps[0].command, ("echo", "launch", "now"))
        self.assertIsNone(result.returncode)

    def test_missing_out_is_rejected_for_command_runtime_that_expands_out(self) -> None:
        registry = ConductorRegistry(
            [
                conductor_manifest(
                    "external.uses_out",
                    {"kind": "command", "command": {"argv": ["echo", "{out}"]}},
                )
            ]
        )

        with self.assertRaisesRegex(ConductorRunnerError, "--out is required"):
            run_conductor(ConductorRunRequest("external.uses_out", dry_run=True), registry)

    def test_missing_out_is_rejected_for_non_dry_run(self) -> None:
        registry = ConductorRegistry(
            [
                conductor_manifest(
                    "external.exec_needs_out",
                    {"kind": "command", "command": {"argv": ["echo", "ok"]}},
                )
            ]
        )

        with self.assertRaisesRegex(ConductorRunnerError, "--out is required for conductor execution"):
            run_conductor(ConductorRunRequest("external.exec_needs_out"), registry)

    def test_build_conductor_command_matches_command_runtime_expansion(self) -> None:
        registry = ConductorRegistry(
            [
                conductor_manifest(
                    "external.command_builder",
                    {"kind": "command", "command": {"argv": ["echo", "{topic}", "{conductor_args}"]}},
                    inputs=[Port("topic", "string")],
                )
            ]
        )

        command = build_conductor_command(
            ConductorRunRequest(
                "external.command_builder",
                out="runs/test",
                inputs={"topic": "launch"},
                conductor_args=("now",),
            ),
            registry,
        )

        self.assertEqual(command, ("echo", "launch", "now"))

    def test_command_runtime_executes_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "result.json"
            registry = ConductorRegistry(
                [
                    conductor_manifest(
                        "external.exec",
                        {
                            "kind": "command",
                            "command": {
                                "argv": [
                                    sys.executable,
                                    "-c",
                                    "import json, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(json.dumps({'ok': True}), encoding='utf-8')",
                                    "{artifact}",
                                ],
                            },
                        },
                        outputs=[Output("artifact", "file")],
                    )
                ]
            )

            result = run_conductor(
                ConductorRunRequest(
                    "external.exec",
                    out=root / "out",
                    outputs={"artifact": output},
                ),
                registry,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])

    def test_python_runtime_imports_and_calls_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module_dir = root / "pkg"
            module_dir.mkdir()
            (module_dir / "__init__.py").write_text("", encoding="utf-8")
            (module_dir / "runtime.py").write_text(
                "\n".join(
                    [
                        "def run(request, conductor):",
                        "    return {",
                        "        'planned_commands': [['python-runtime', conductor.id, request.conductor_args[0]]],",
                        "        'returncode': 5,",
                        "        'outputs': {'out': str(request.out)},",
                        "    }",
                    ]
                ),
                encoding="utf-8",
            )
            sys.path.insert(0, str(root))
            self.addCleanup(lambda: sys.path.remove(str(root)) if str(root) in sys.path else None)
            registry = ConductorRegistry(
                [
                    conductor_manifest(
                        "external.python",
                        {"kind": "python", "module": "pkg.runtime", "function": "run"},
                    )
                ]
            )

            result = run_conductor(
                ConductorRunRequest(
                    "external.python",
                    out=root / "out",
                    conductor_args=("plan",),
                    dry_run=True,
                ),
                registry,
            )

        self.assertIsNone(result.returncode)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.planned_commands, (("python-runtime", "external.python", "plan"),))
        self.assertTrue(result.outputs["out"].endswith("/out"))

    def test_python_runtime_can_return_result_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module_dir = root / "pkg_result"
            module_dir.mkdir()
            (module_dir / "__init__.py").write_text("", encoding="utf-8")
            (module_dir / "runtime.py").write_text(
                "\n".join(
                    [
                        "from artagents.conductors.runner import ConductorRunResult",
                        "def run(request, conductor):",
                        "    return ConductorRunResult(",
                        "        conductor_id=conductor.id,",
                        "        kind=conductor.kind,",
                        "        runtime_kind='python',",
                        "        planned_commands=(('object-result',),),",
                        "        returncode=None,",
                        "        dry_run=request.dry_run,",
                        "    )",
                    ]
                ),
                encoding="utf-8",
            )
            sys.path.insert(0, str(root))
            self.addCleanup(lambda: sys.path.remove(str(root)) if str(root) in sys.path else None)
            registry = ConductorRegistry(
                [
                    conductor_manifest(
                        "external.python_result",
                        {"kind": "python", "module": "pkg_result.runtime", "function": "run"},
                    )
                ]
            )

            result = run_conductor(ConductorRunRequest("external.python_result", out=root, dry_run=True), registry)

        self.assertIsInstance(result, ConductorRunResult)
        self.assertEqual(result.planned_commands, (("object-result",),))
        self.assertEqual(result.plan.steps[0].command, ("object-result",))
        self.assertIsNone(result.returncode)

    def test_python_runtime_can_return_structured_plan_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module_dir = root / "pkg_plan"
            module_dir.mkdir()
            (module_dir / "__init__.py").write_text("", encoding="utf-8")
            (module_dir / "runtime.py").write_text(
                "\n".join(
                    [
                        "def run(request, conductor):",
                        "    return {",
                        "        'planned_commands': [['custom-plan-command']],",
                        "        'plan': {'steps': [{'id': 'custom.step', 'kind': 'command', 'command': ['custom-plan-command'], 'metadata': {'source': conductor.id}}]},",
                        "        'dry_run': request.dry_run,",
                        "    }",
                    ]
                ),
                encoding="utf-8",
            )
            sys.path.insert(0, str(root))
            self.addCleanup(lambda: sys.path.remove(str(root)) if str(root) in sys.path else None)
            registry = ConductorRegistry(
                [
                    conductor_manifest(
                        "external.python_plan",
                        {"kind": "python", "module": "pkg_plan.runtime", "function": "run"},
                    )
                ]
            )

            result = run_conductor(ConductorRunRequest("external.python_plan", dry_run=True), registry)

        self.assertEqual(result.planned_commands, (("custom-plan-command",),))
        self.assertEqual(result.plan.steps[0].id, "custom.step")
        self.assertEqual(result.to_dict()["plan"]["steps"][0]["metadata"]["source"], "external.python_plan")

    def test_result_to_dict_includes_explicit_structured_plan(self) -> None:
        explicit = ConductorRunResult(
            conductor_id="external.explicit",
            kind="external",
            runtime_kind="python",
            planned_commands=(("explicit-command",),),
            dry_run=True,
            plan=ConductorPlan(steps=(ConductorPlanStep(id="explicit.step", command=("explicit-command",)),)),
        )
        self.assertEqual(explicit.to_dict()["plan"]["steps"][0]["id"], "explicit.step")

    def test_missing_required_input_fails_before_runtime(self) -> None:
        registry = ConductorRegistry(
            [
                conductor_manifest(
                    "external.needs_topic",
                    {"kind": "command", "command": {"argv": ["echo", "{topic}"]}},
                    inputs=[Port("topic", "string")],
                )
            ]
        )

        with self.assertRaisesRegex(ConductorRunnerError, "missing required input"):
            run_conductor(ConductorRunRequest("external.needs_topic", out="runs/test", dry_run=True), registry)

    def test_missing_placeholder_value_fails_clearly(self) -> None:
        registry = ConductorRegistry(
            [
                conductor_manifest(
                    "external.missing_placeholder",
                    {"kind": "command", "command": {"argv": ["echo", "{topic}"]}},
                    inputs=[Port("topic", "string", required=False)],
                )
            ]
        )

        with self.assertRaisesRegex(ConductorRunnerError, r"missing value for placeholder \{topic\}"):
            run_conductor(ConductorRunRequest("external.missing_placeholder", out="runs/test", dry_run=True), registry)

    def test_performer_modules_do_not_import_conductors(self) -> None:
        offenders: list[str] = []
        for path in sorted(Path("artagents/performers").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            if _module_imports_conductors(tree):
                offenders.append(str(path))

        self.assertEqual(offenders, [])

def _module_imports_conductors(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "artagents.conductors" or alias.name.startswith("artagents.conductors."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "artagents.conductors" or module.startswith("artagents.conductors."):
                return True
        elif isinstance(node, ast.Call) and _call_name(node.func) in {"import_module", "__import__"}:
            if node.args and _string_expr_value(node.args[0]).startswith("artagents.conductors"):
                return True
    return False


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


if __name__ == "__main__":
    unittest.main()


def _string_expr_value(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _string_expr_value(node.left)
        right = _string_expr_value(node.right)
        if left or right:
            return left + right
    return ""
