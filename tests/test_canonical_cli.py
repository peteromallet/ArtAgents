import contextlib
import io
import json
import unittest
from unittest import mock

from astrid import pipeline
from astrid.core.element import cli as elements_cli
from astrid.core.executor import cli as executors_cli
from astrid.core.executor.schema import (
    ExecutorValidationError,
    validate_executor_definition,
)
from astrid.core.orchestrator import cli as orchestrators_cli


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
        self.assertIn("Astrid orchestrators", help_text)
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
        self.assertIn("Astrid executors", help_text)
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
        self.assertIn("astrid.packs.builtin.render.run", stdout)

    def test_pipeline_dispatches_canonical_cli_modules(self) -> None:
        with mock.patch.object(orchestrators_cli, "main", return_value=61) as main:
            self.assertEqual(pipeline.main(["orchestrators", "list"]), 61)
            main.assert_called_once_with(["list"])
        with mock.patch.object(executors_cli, "main", return_value=62) as main:
            self.assertEqual(pipeline.main(["executors", "list"]), 62)
            main.assert_called_once_with(["list"])

    def test_lifecycle_start_short_circuits_gate(self) -> None:
        """T21: pipeline.main(['start', ...]) routes to lifecycle.cmd_start
        without invoking the implicit task_gate. Existing orchestrators/
        executors paths remain unchanged.
        """
        from astrid.core.task import gate as task_gate
        from astrid.core.task import lifecycle as lifecycle_module

        with (
            mock.patch.object(lifecycle_module, "cmd_start", return_value=71) as cmd_start_mock,
            mock.patch.object(task_gate, "gate_command") as gate_mock,
        ):
            rc = pipeline.main(["start", "demo.app", "--project", "p", "--name", "r1"])
        self.assertEqual(rc, 71)
        cmd_start_mock.assert_called_once_with(
            ["demo.app", "--project", "p", "--name", "r1"]
        )
        # Critical: the implicit gate at the top of main() must NOT be invoked
        # for lifecycle verbs. cmd_ack approve re-enters the gate explicitly,
        # but for `start --project p` the project slug is the run target, not
        # a command to dispatch through plan[cursor].
        self.assertEqual(
            gate_mock.call_count,
            0,
            "task_gate.gate_command must not be called for lifecycle verbs",
        )

        # Sanity-check the other lifecycle verbs short-circuit the same way.
        for verb, attr, rc_marker in [
            ("next", "cmd_next", 72),
            ("ack", "cmd_ack", 73),
            ("abort", "cmd_abort", 74),
            ("status", "cmd_status", 75),
            ("runs", "cmd_runs_ls", 76),
        ]:
            with (
                mock.patch.object(lifecycle_module, attr, return_value=rc_marker),
                mock.patch.object(task_gate, "gate_command") as gate_mock,
            ):
                argv = ["runs", "ls", "--project", "p"] if verb == "runs" else [verb, "--project", "p"]
                rc = pipeline.main(argv)
            self.assertEqual(rc, rc_marker, f"{verb} should route to lifecycle.{attr}")
            self.assertEqual(
                gate_mock.call_count, 0, f"gate_command called for `{verb}`"
            )

        # Confirm orchestrators list / executors list paths still work
        # unchanged after the lifecycle short-circuit was added (no shadow).
        with mock.patch.object(orchestrators_cli, "main", return_value=81) as main:
            self.assertEqual(pipeline.main(["orchestrators", "list"]), 81)
            main.assert_called_once_with(["list"])
        with mock.patch.object(executors_cli, "main", return_value=82) as main:
            self.assertEqual(pipeline.main(["executors", "list"]), 82)
            main.assert_called_once_with(["list"])


class CapabilityDiscoveryTest(unittest.TestCase):
    def capture(self, fn, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = fn(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_executors_list_includes_short_description_column(self) -> None:
        result, stdout, stderr = self.capture(executors_cli.main, ["list"])
        self.assertEqual(result, 0, stderr)
        moirae_line = next(
            line for line in stdout.splitlines() if line.startswith("external.moirae\t")
        )
        # id, kind, name, short_description = 4 tab-separated columns
        self.assertEqual(moirae_line.count("\t"), 3)
        self.assertIn("Moirae", moirae_line)
        self.assertIn("terminal", moirae_line.lower())

    def test_executors_list_no_describe_drops_column(self) -> None:
        result, stdout, stderr = self.capture(executors_cli.main, ["list", "--no-describe"])
        self.assertEqual(result, 0, stderr)
        moirae_line = next(
            line for line in stdout.splitlines() if line.startswith("external.moirae\t")
        )
        self.assertEqual(moirae_line.count("\t"), 2)

    def test_executors_search_ranks_terminal_video_for_moirae(self) -> None:
        result, stdout, stderr = self.capture(
            executors_cli.main, ["search", "terminal", "video"]
        )
        self.assertEqual(result, 0, stderr)
        first_line = stdout.splitlines()[0]
        # score \t id \t kind \t short_description
        parts = first_line.split("\t")
        self.assertEqual(parts[1], "external.moirae", first_line)

    def test_executors_search_json_returns_hits(self) -> None:
        result, stdout, stderr = self.capture(
            executors_cli.main, ["search", "transcribe", "--json"]
        )
        self.assertEqual(result, 0, stderr)
        payload = json.loads(stdout)
        self.assertIn("hits", payload)
        ids = [hit["id"] for hit in payload["hits"]]
        self.assertIn("builtin.transcribe", ids)

    def test_executor_run_inputs_normalize_dashes_and_combine_repeats(self) -> None:
        parsed = executors_cli._parse_input_values(
            ["match-mode=any", "match=photo", "match=realism"]
        )
        self.assertEqual(parsed["match_mode"], "any")
        self.assertEqual(parsed["match"], "photo,realism")

    def test_orchestrators_search_finds_foley_pipeline(self) -> None:
        result, stdout, stderr = self.capture(
            orchestrators_cli.main, ["search", "foley", "spatial"]
        )
        self.assertEqual(result, 0, stderr)
        first_line = stdout.splitlines()[0]
        self.assertIn("builtin.foley_map", first_line)

    def test_elements_search_finds_fade_animation(self) -> None:
        result, stdout, stderr = self.capture(elements_cli.main, ["search", "fade"])
        self.assertEqual(result, 0, stderr)
        ids = [line.split("\t")[1] for line in stdout.splitlines() if line.strip()]
        self.assertIn("fade", ids)

    def test_schema_rejects_over_cap_description(self) -> None:
        with self.assertRaises(ExecutorValidationError) as ctx:
            validate_executor_definition(
                {
                    "id": "demo.over",
                    "name": "Demo",
                    "kind": "built_in",
                    "version": "1.0",
                    "description": "x" * 501,
                }
            )
        self.assertIn("description", str(ctx.exception))
        self.assertIn("501", str(ctx.exception))
        self.assertIn("demo.over", str(ctx.exception))

    def test_schema_rejects_over_cap_short_description(self) -> None:
        with self.assertRaises(ExecutorValidationError) as ctx:
            validate_executor_definition(
                {
                    "id": "demo.over",
                    "name": "Demo",
                    "kind": "built_in",
                    "version": "1.0",
                    "short_description": "y" * 121,
                }
            )
        self.assertIn("short_description", str(ctx.exception))

    def test_schema_rejects_uppercase_keyword(self) -> None:
        with self.assertRaises(ExecutorValidationError) as ctx:
            validate_executor_definition(
                {
                    "id": "demo.over",
                    "name": "Demo",
                    "kind": "built_in",
                    "version": "1.0",
                    "keywords": ["Video"],
                }
            )
        self.assertIn("lowercase", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
