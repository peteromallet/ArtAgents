import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents import pipeline
from artagents.conductors import cli
from artagents.conductors.registry import ConductorRegistry, load_default_registry as load_real_default_registry


def conductor_manifest(conductor_id: str, *, kind: str = "external") -> dict:
    return {
        "id": conductor_id,
        "name": conductor_id.replace(".", " ").title(),
        "kind": kind,
        "version": "1.0",
        "description": "Test conductor",
        "runtime": {
            "kind": "command",
            "command": {
                "argv": [
                    "echo",
                    "{topic}",
                    "{brief}",
                    "{python_exec}",
                    "{conductor_args}",
                ]
            },
        },
        "inputs": [{"name": "topic", "type": "string"}],
        "cache": {"mode": "none"},
    }


class ConductorCliTest(unittest.TestCase):
    def registry(self) -> ConductorRegistry:
        return ConductorRegistry(
            [
                conductor_manifest("external.echo"),
                conductor_manifest("built_in.sample", kind="built_in"),
            ]
        )

    def invoke(self, argv: list[str], registry: ConductorRegistry | None = None) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(cli, "load_default_registry", return_value=registry or self.registry()),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = cli.main(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_list_json_and_kind_filter(self) -> None:
        result, stdout, stderr = self.invoke(["list", "--json", "--kind", "built_in"])

        self.assertEqual(result, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual([item["id"] for item in payload["conductors"]], ["built_in.sample"])

    def test_list_text_outputs_conductors(self) -> None:
        result, stdout, stderr = self.invoke(["list"])

        self.assertEqual(result, 0, stderr)
        self.assertIn("external.echo\texternal\tExternal Echo", stdout)
        self.assertIn("built_in.sample\tbuilt_in\tBuilt_In Sample", stdout)

    def test_banodoco_flags_are_passed_to_registry(self) -> None:
        registry = self.registry()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(cli, "load_default_registry", return_value=registry) as load_registry:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = cli.main(
                    [
                        "--banodoco-agent-conductors",
                        "--banodoco-catalog-url",
                        "https://example.test/catalog",
                        "--banodoco-cache-dir",
                        "/tmp/catalog-cache",
                        "--banodoco-refresh",
                        "--no-banodoco-defaults",
                        "list",
                    ]
                )

        self.assertEqual(result, 0, stderr.getvalue())
        config = load_registry.call_args.kwargs["banodoco_config"]
        self.assertTrue(config.enabled)
        self.assertEqual(config.catalog_url, "https://example.test/catalog")
        self.assertEqual(str(config.cache_dir), "/tmp/catalog-cache")
        self.assertTrue(config.refresh)
        self.assertFalse(config.include_defaults)
        self.assertIn("external.echo", stdout.getvalue())

    def test_inspect_json_outputs_conductor_metadata(self) -> None:
        result, stdout, stderr = self.invoke(["inspect", "external.echo", "--json"])

        self.assertEqual(result, 0, stderr)
        conductor = json.loads(stdout)
        self.assertEqual(conductor["id"], "external.echo")
        self.assertEqual(conductor["runtime"]["kind"], "command")

    def test_inspect_text_outputs_runtime_and_inputs(self) -> None:
        result, stdout, stderr = self.invoke(["inspect", "external.echo"])

        self.assertEqual(result, 0, stderr)
        self.assertIn("runtime: command", stdout)
        self.assertIn("inputs:", stdout)
        self.assertIn("command: echo", stdout)

    def test_validate_all_and_one(self) -> None:
        result_all, stdout_all, stderr_all = self.invoke(["validate"])
        result_one, stdout_one, stderr_one = self.invoke(["validate", "external.echo"])

        self.assertEqual(result_all, 0, stderr_all)
        self.assertIn("2 conductor(s): ok", stdout_all)
        self.assertEqual(result_one, 0, stderr_one)
        self.assertIn("external.echo: ok", stdout_one)

    def test_run_dry_run_expands_inputs_and_passthrough_after_separator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brief = root / "brief.txt"
            brief.write_text("brief", encoding="utf-8")

            result, stdout, stderr = self.invoke(
                [
                    "run",
                    "external.echo",
                    "--out",
                    str(root / "out"),
                    "--brief",
                    str(brief),
                    "--input",
                    "topic=launch",
                    "--python-exec",
                    "/tmp/python",
                    "--dry-run",
                    "--verbose",
                    "--",
                    "--flag",
                    "value",
                ]
            )

        self.assertEqual(result, 0, stderr)
        self.assertIn("echo launch", stdout)
        self.assertIn(str(brief), stdout)
        self.assertIn("/tmp/python", stdout)
        self.assertIn("--flag value", stdout)

    def test_run_dry_run_allows_omitted_out_when_runtime_does_not_use_it(self) -> None:
        result, stdout, stderr = self.invoke(
            [
                "run",
                "external.echo",
                "--brief",
                "brief.txt",
                "--input",
                "topic=launch",
                "--dry-run",
            ]
        )

        self.assertEqual(result, 0, stderr)
        self.assertIn("echo launch", stdout)

    def test_run_dry_run_rejects_missing_out_when_runtime_uses_it(self) -> None:
        registry = ConductorRegistry(
            [
                {
                    **conductor_manifest("external.uses_out"),
                    "runtime": {"kind": "command", "command": {"argv": ["echo", "{out}"]}},
                }
            ]
        )

        result, stdout, stderr = self.invoke(["run", "external.uses_out", "--dry-run"], registry=registry)

        self.assertEqual(result, 2)
        self.assertEqual(stdout, "")
        self.assertIn("--out is required", stderr)

    def test_builtin_event_talks_dry_run_can_omit_generic_out(self) -> None:
        with mock.patch("artagents.event_talks.main", side_effect=AssertionError("legacy CLI should not run")):
            result, stdout, stderr = self.invoke(
                [
                    "run",
                    "builtin.event_talks",
                    "--dry-run",
                    "--",
                    "ados-sunday-template",
                    "--out",
                    "talks.json",
                ],
                registry=load_real_default_registry(),
            )

        self.assertEqual(result, 0, stderr)
        self.assertEqual(stdout.strip(), "event_talks.py ados-sunday-template --out talks.json")
        self.assertNotIn("plan", stdout)

    def test_builtin_hype_dry_run_rejects_missing_out(self) -> None:
        result, stdout, stderr = self.invoke(
            [
                "run",
                "builtin.hype",
                "--dry-run",
                "--brief",
                "brief.txt",
            ],
            registry=load_real_default_registry(),
        )

        self.assertEqual(result, 2)
        self.assertEqual(stdout, "")
        self.assertIn("--out is required for builtin.hype dry-run", stderr)

    def test_unknown_conductor_returns_status_2(self) -> None:
        result, stdout, stderr = self.invoke(["inspect", "external.missing"])

        self.assertEqual(result, 2)
        self.assertEqual(stdout, "")
        self.assertIn("unknown conductor id", stderr)

    def test_invalid_input_syntax_returns_status_2(self) -> None:
        result, stdout, stderr = self.invoke(
            [
                "run",
                "external.echo",
                "--out",
                "runs/test",
                "--input",
                "broken",
                "--dry-run",
            ]
        )

        self.assertEqual(result, 2)
        self.assertEqual(stdout, "")
        self.assertIn("invalid --input value", stderr)

    def test_pipeline_dispatches_conductors_before_legacy_validation(self) -> None:
        with mock.patch.object(cli, "main", return_value=17) as conductor_main:
            result = pipeline.main(["conductors", "list"])

        self.assertEqual(result, 17)
        conductor_main.assert_called_once_with(["list"])

    def test_pipeline_performers_dispatch_still_works(self) -> None:
        from artagents.performers import cli as performers_cli

        with mock.patch.object(performers_cli, "main", return_value=23) as performers_main:
            result = pipeline.main(["performers", "list"])

        self.assertEqual(result, 23)
        performers_main.assert_called_once_with(["list"])


if __name__ == "__main__":
    unittest.main()
