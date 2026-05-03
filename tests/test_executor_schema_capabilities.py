from __future__ import annotations

import argparse
import contextlib
import io
import json
import unittest

from artagents.executors import cli as executors_cli
from artagents.executors.registry import ExecutorRegistry
from artagents.executors.schema import ExecutorValidationError, validate_executor_definition


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


if __name__ == "__main__":
    unittest.main()
