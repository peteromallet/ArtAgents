from __future__ import annotations

import contextlib
import io
import unittest

from artagents.core.executor import cli as executors_cli
from artagents.core.executor.schema import ExecutorValidationError, validate_executor_definition
from artagents.core.orchestrator import cli as orchestrators_cli
from artagents.core.orchestrator.schema import OrchestratorValidationError, validate_orchestrator_definition


def _capture(fn, argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = fn(argv)
    return result, stdout.getvalue(), stderr.getvalue()


class QualifiedIdEnforcementTest(unittest.TestCase):
    def test_executor_schema_rejects_bare_ids(self) -> None:
        with self.assertRaisesRegex(ExecutorValidationError, "executor.id must be qualified"):
            validate_executor_definition(
                {
                    "id": "cut",
                    "name": "Cut",
                    "kind": "built_in",
                    "version": "1.0",
                }
            )

    def test_executor_schema_rejects_bare_dependencies(self) -> None:
        with self.assertRaisesRegex(ExecutorValidationError, "graph.depends_on"):
            validate_executor_definition(
                {
                    "id": "builtin.cut",
                    "name": "Cut",
                    "kind": "built_in",
                    "version": "1.0",
                    "graph": {"depends_on": ["transcribe"]},
                }
            )

    def test_orchestrator_schema_rejects_bare_ids_and_children(self) -> None:
        with self.assertRaisesRegex(OrchestratorValidationError, "orchestrator.id must be qualified"):
            validate_orchestrator_definition(
                {
                    "id": "hype",
                    "name": "Hype",
                    "kind": "built_in",
                    "version": "1.0",
                    "runtime": {"kind": "command", "command": {"argv": ["echo", "ok"]}},
                }
            )

        with self.assertRaisesRegex(OrchestratorValidationError, "orchestrator.child_executors"):
            validate_orchestrator_definition(
                {
                    "id": "builtin.hype",
                    "name": "Hype",
                    "kind": "built_in",
                    "version": "1.0",
                    "runtime": {"kind": "command", "command": {"argv": ["echo", "ok"]}},
                    "child_executors": ["cut"],
                }
            )

    def test_cli_rejects_bare_executor_lookup_and_accepts_qualified_id(self) -> None:
        result, _, stderr = _capture(executors_cli.main, ["inspect", "cut"])
        self.assertEqual(result, 2)
        self.assertIn("executor id must be qualified", stderr)

        result, stdout, stderr = _capture(executors_cli.main, ["inspect", "builtin.cut"])
        self.assertEqual(result, 0, stderr)
        self.assertIn("id: builtin.cut", stdout)

    def test_cli_rejects_bare_orchestrator_lookup_and_accepts_qualified_id(self) -> None:
        result, _, stderr = _capture(orchestrators_cli.main, ["inspect", "hype"])
        self.assertEqual(result, 2)
        self.assertIn("orchestrator id must be qualified", stderr)

        result, stdout, stderr = _capture(orchestrators_cli.main, ["inspect", "builtin.hype"])
        self.assertEqual(result, 0, stderr)
        self.assertIn("id: builtin.hype", stdout)


if __name__ == "__main__":
    unittest.main()
