import contextlib
import io
import json
import unittest
from unittest import mock

from artagents import pipeline
from artagents.core.executor import cli as executors_cli
from artagents.core.orchestrator import cli as orchestrators_cli


class CanonicalCliTest(unittest.TestCase):
    def capture(self, fn, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = fn(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_orchestrators_json_uses_canonical_key(self) -> None:
        result, stdout, stderr = self.capture(orchestrators_cli.main, ["list", "--json"])
        self.assertEqual(result, 0, stderr)
        payload = json.loads(stdout)
        self.assertIn("orchestrators", payload)
        self.assertNotIn("conductors", payload)
        self.assertIn("builtin.hype", {item["id"] for item in payload["orchestrators"]})

    def test_orchestrator_help_uses_canonical_terms(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(stdout):
            orchestrators_cli.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("ArtAgents orchestrators", help_text)
        self.assertNotIn("conductors", help_text)
        self.assertNotIn("performers", help_text)

    def test_executors_json_uses_canonical_key(self) -> None:
        result, stdout, stderr = self.capture(executors_cli.main, ["list", "--json"])
        self.assertEqual(result, 0, stderr)
        payload = json.loads(stdout)
        self.assertIn("executors", payload)
        self.assertNotIn("performers", payload)
        self.assertIn("builtin.render", {item["id"] for item in payload["executors"]})

    def test_executor_help_uses_canonical_terms(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(stdout):
            executors_cli.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("ArtAgents executors", help_text)
        self.assertNotIn("performers", help_text)
        self.assertNotIn("instruments", help_text)

    def test_canonical_validate_install_and_run_paths(self) -> None:
        result, stdout, stderr = self.capture(orchestrators_cli.main, ["validate", "builtin.hype"])
        self.assertEqual(result, 0, stderr)
        self.assertIn("builtin.hype: ok", stdout)

        result, stdout, stderr = self.capture(executors_cli.main, ["validate", "builtin.render"])
        self.assertEqual(result, 0, stderr)
        self.assertIn("builtin.render: ok", stdout)

        result, stdout, stderr = self.capture(executors_cli.main, ["install", "builtin.render", "--dry-run"])
        self.assertEqual(result, 0, stderr)
        self.assertIn("no install needed", stdout)

        result, stdout, stderr = self.capture(
            executors_cli.main,
            ["run", "builtin.render", "--out", "runs/example", "--brief", "brief.txt", "--dry-run"],
        )
        self.assertEqual(result, 0, stderr)
        self.assertIn("artagents.packs.builtin.render.run", stdout)

    def test_pipeline_dispatches_canonical_cli_modules(self) -> None:
        with mock.patch.object(orchestrators_cli, "main", return_value=61) as main:
            self.assertEqual(pipeline.main(["orchestrators", "list"]), 61)
            main.assert_called_once_with(["list"])
        with mock.patch.object(executors_cli, "main", return_value=62) as main:
            self.assertEqual(pipeline.main(["executors", "list"]), 62)
            main.assert_called_once_with(["list"])


if __name__ == "__main__":
    unittest.main()
