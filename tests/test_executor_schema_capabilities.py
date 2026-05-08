from __future__ import annotations

import argparse
import contextlib
import io
import json
import unittest

from astrid.core.executor import cli as executors_cli
from astrid.core.executor.registry import ExecutorRegistry
from astrid.core.executor.schema import ExecutorValidationError, validate_executor_definition


def _manifest(**overrides):
    data = {
        "id": "builtin.demo",
        "name": "Demo",
        "kind": "built_in",
        "version": "1.0",
        "description": "Demo executor.",
    }
    data.update(overrides)
    return data


class ExecutorSchemaCapabilityTest(unittest.TestCase):
    def test_clip_kinds_and_requirements_round_trip(self) -> None:
        executor = validate_executor_definition(
            _manifest(
                clip_kinds_supported=["VIDEO", "image"],
                pipeline_requirements=["brief", "pool"],
            )
        )

        self.assertEqual(executor.clip_kinds_supported, ("video", "image"))
        self.assertEqual(executor.pipeline_requirements, ("brief", "pool"))
        payload = executor.to_dict()
        self.assertEqual(payload["clip_kinds_supported"], ["video", "image"])
        self.assertEqual(payload["pipeline_requirements"], ["brief", "pool"])

    def test_inspect_json_exposes_capability_fields(self) -> None:
        executor = validate_executor_definition(
            _manifest(
                clip_kinds_supported=["audio"],
                pipeline_requirements=["transcript"],
            )
        )
        registry = ExecutorRegistry([executor])
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            result = executors_cli._cmd_inspect(
                argparse.Namespace(executor_id="builtin.demo", json=True),
                registry,
            )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["clip_kinds_supported"], ["audio"])
        self.assertEqual(payload["pipeline_requirements"], ["transcript"])

    def test_invalid_clip_kind_rejected(self) -> None:
        with self.assertRaisesRegex(ExecutorValidationError, "clip_kinds_supported"):
            validate_executor_definition(_manifest(clip_kinds_supported=["banana"]))

    def test_invalid_pipeline_requirement_rejected(self) -> None:
        with self.assertRaisesRegex(ExecutorValidationError, "pipeline_requirements"):
            validate_executor_definition(_manifest(pipeline_requirements=["banana"]))

    def test_deprecated_produces_for_alias_normalizes_without_round_trip(self) -> None:
        executor = validate_executor_definition(_manifest(produces_for=["AUDIO", "TEXT"]))

        self.assertEqual(executor.clip_kinds_supported, ("audio", "text"))
        payload = executor.to_dict()
        self.assertEqual(payload["clip_kinds_supported"], ["audio", "text"])
        self.assertNotIn("produces_for", payload)

    def test_external_runtime_package_metadata_and_output_extension_parse(self) -> None:
        executor = validate_executor_definition(
            _manifest(
                id="external.demo",
                kind="external",
                outputs=[{"name": "video", "extension": ".mp4"}],
                metadata={
                    "external_runtime": {
                        "mode": "package",
                        "source": {
                            "kind": "git",
                            "url": "https://example.invalid/demo.git",
                            "ref": "abc123",
                        },
                        "install": {"strategy": "pyproject", "target": "pyproject.toml"},
                        "import_check": "demo_pkg.cli",
                        "binary_check": ["ffmpeg"],
                    },
                    "legacy": {"preserved": True},
                },
            )
        )

        self.assertEqual(executor.outputs[0].extension, ".mp4")
        self.assertEqual(executor.external_runtime.mode, "package")
        self.assertEqual(executor.external_runtime.source.kind, "git")
        self.assertEqual(executor.external_runtime.source.ref, "abc123")
        self.assertEqual(executor.external_runtime.install.strategy, "pyproject")
        self.assertEqual(executor.external_runtime.binary_check, ("ffmpeg",))
        payload = executor.to_dict()
        self.assertEqual(payload["outputs"][0]["extension"], ".mp4")
        self.assertEqual(payload["metadata"]["legacy"], {"preserved": True})
        self.assertEqual(payload["metadata"]["external_runtime"]["source"]["url"], "https://example.invalid/demo.git")
        self.assertNotIn("external_runtime", {key for key in payload if key != "metadata"})

    def test_external_runtime_api_mode_does_not_require_source_or_install(self) -> None:
        executor = validate_executor_definition(
            _manifest(
                id="external.api",
                kind="external",
                metadata={"external_runtime": {"mode": "api", "binary_check": ["curl"]}},
            )
        )

        self.assertEqual(executor.external_runtime.mode, "api")
        self.assertIsNone(executor.external_runtime.source)
        self.assertIsNone(executor.external_runtime.install)

    def test_external_runtime_rejects_package_missing_source_or_install(self) -> None:
        with self.assertRaisesRegex(ExecutorValidationError, "source is required"):
            validate_executor_definition(
                _manifest(
                    id="external.demo",
                    kind="external",
                    metadata={
                        "external_runtime": {
                            "mode": "package",
                            "install": {"strategy": "pyproject", "target": "pyproject.toml"},
                        }
                    },
                )
            )
        with self.assertRaisesRegex(ExecutorValidationError, "install is required"):
            validate_executor_definition(
                _manifest(
                    id="external.demo",
                    kind="external",
                    metadata={
                        "external_runtime": {
                            "mode": "package",
                            "source": {"kind": "pypi", "package": "demo"},
                        }
                    },
                )
            )

    def test_external_runtime_rejects_api_source_or_install(self) -> None:
        with self.assertRaisesRegex(ExecutorValidationError, "api.*source or install"):
            validate_executor_definition(
                _manifest(
                    id="external.api",
                    kind="external",
                    metadata={
                        "external_runtime": {
                            "mode": "api",
                            "source": {"kind": "pypi", "package": "demo"},
                        }
                    },
                )
            )

    def test_external_runtime_rejects_invalid_source_install_import_and_binary(self) -> None:
        invalid_cases = [
            (
                {
                    "source": {"kind": "git", "ref": "main"},
                    "install": {"strategy": "pyproject", "target": "pyproject.toml"},
                },
                "source.url",
            ),
            (
                {
                    "source": {"kind": "path", "url": "https://example.invalid/repo.git", "path": "/tmp/repo"},
                    "install": {"strategy": "requirements", "target": "requirements.txt"},
                },
                "source.url",
            ),
            (
                {
                    "source": {"kind": "pypi", "package": "demo"},
                    "install": {"strategy": "unknown", "target": "requirements.txt"},
                },
                "install.strategy",
            ),
            (
                {
                    "source": {"kind": "pypi", "package": "demo"},
                    "install": {"strategy": "pip_args", "target": "demo"},
                    "import_check": "demo-package",
                },
                "import_check",
            ),
            (
                {
                    "source": {"kind": "pypi", "package": "demo"},
                    "install": {"strategy": "pip_args", "target": "demo"},
                    "binary_check": [""],
                },
                "binary_check",
            ),
        ]
        for external_runtime, expected in invalid_cases:
            with self.subTest(expected=expected), self.assertRaisesRegex(ExecutorValidationError, expected):
                validate_executor_definition(
                    _manifest(
                        id="external.demo",
                        kind="external",
                        metadata={"external_runtime": external_runtime},
                    )
                )

    def test_external_runtime_rejects_invalid_output_extension(self) -> None:
        invalid_outputs = [
            ({"name": "video", "extension": "mp4"}, "start with"),
            ({"name": "video", "extension": ".thisextensionistoolong"}, "16 characters"),
            ({"name": "video", "extension": "../mp4"}, "path separators"),
        ]
        for output, expected in invalid_outputs:
            with self.subTest(output=output), self.assertRaisesRegex(ExecutorValidationError, expected):
                validate_executor_definition(_manifest(outputs=[output]))


if __name__ == "__main__":
    unittest.main()
