import json
import tempfile
import unittest
from pathlib import Path

from artagents.contracts import schema as contracts_schema
from artagents.conductors import (
    CachePolicy,
    CommandSpec as ExportedCommandSpec,
    ConductorSpec,
    ConductorValidationError,
    RuntimeSpec,
    conductor,
    load_conductor_manifest,
    validate_conductor_definition,
)
from artagents.conductors import schema as conductors_schema
from artagents.performers import CommandSpec, PerformerOutput, PerformerPort, validate_performer_definition
from artagents.performers import schema as performers_schema


class ConductorSchemaTest(unittest.TestCase):
    def valid_manifest(self) -> dict:
        return {
            "id": "example.conductor",
            "name": "Example Conductor",
            "kind": "external",
            "version": "1.0",
            "runtime": {"kind": "python", "module": "example.runtime", "function": "run"},
            "inputs": [{"name": "brief", "type": "file"}],
            "outputs": [{"name": "manifest", "type": "file", "placeholder": "manifest_out"}],
            "child_performers": ["builtin.transcribe"],
            "child_conductors": ["external.child"],
            "cache": {"mode": "none"},
            "isolation": {"mode": "subprocess", "network": False},
        }

    def test_valid_python_runtime_round_trips_to_stable_json(self) -> None:
        definition = validate_conductor_definition(self.valid_manifest())

        self.assertEqual(definition.id, "example.conductor")
        encoded = definition.to_json()
        decoded = json.loads(encoded)
        self.assertEqual(decoded["runtime"]["kind"], "python")
        self.assertEqual(decoded["runtime"]["module"], "example.runtime")
        self.assertEqual(decoded["child_performers"], ["builtin.transcribe"])
        self.assertEqual(decoded["outputs"][0]["placeholder"], "manifest_out")

    def test_shared_contract_aliases_preserve_identity_and_shape(self) -> None:
        self.assertIs(contracts_schema.CommandSpec, performers_schema.CommandSpec)
        self.assertIs(contracts_schema.CommandSpec, conductors_schema.CommandSpec)
        self.assertIs(contracts_schema.CommandSpec, ExportedCommandSpec)
        self.assertIs(contracts_schema.CommandSpec, CommandSpec)
        self.assertIs(contracts_schema.PerformerPort, conductors_schema.Port)
        self.assertIs(contracts_schema.PerformerPort, PerformerPort)
        self.assertIs(contracts_schema.PerformerOutput, conductors_schema.Output)
        self.assertIs(contracts_schema.PerformerOutput, PerformerOutput)
        self.assertIs(contracts_schema.CachePolicy, CachePolicy)

        definition = validate_conductor_definition(self.valid_manifest())

        self.assertEqual(
            definition.to_dict(),
            {
                "id": "example.conductor",
                "name": "Example Conductor",
                "kind": "external",
                "version": "1.0",
                "runtime": {"kind": "python", "module": "example.runtime", "function": "run"},
                "description": "",
                "inputs": [
                    {
                        "name": "brief",
                        "type": "file",
                        "required": True,
                        "description": "",
                    }
                ],
                "outputs": [
                    {
                        "name": "manifest",
                        "type": "file",
                        "mode": "create_or_replace",
                        "description": "",
                        "placeholder": "manifest_out",
                    }
                ],
                "child_performers": ["builtin.transcribe"],
                "child_conductors": ["external.child"],
                "cache": {
                    "mode": "none",
                    "sentinels": [],
                    "always_run": False,
                    "per_brief": False,
                },
                "isolation": {
                    "mode": "subprocess",
                    "requirements": [],
                    "binaries": [],
                    "network": False,
                },
                "metadata": {},
            },
        )

    def test_valid_command_runtime_round_trips(self) -> None:
        raw = self.valid_manifest()
        raw["runtime"] = {
            "kind": "command",
            "command": {
                "argv": ["{python_exec}", "-m", "example", "{brief}", "--out", "{manifest_out}"],
                "env": {"ARTAGENTS_OUT": "{out}"},
            },
        }

        definition = validate_conductor_definition(raw)

        self.assertEqual(definition.runtime.command.argv[-1], "{manifest_out}")
        self.assertEqual(definition.runtime.command.env["ARTAGENTS_OUT"], "{out}")

    def test_load_conductor_manifest_reads_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conductor.json"
            path.write_text(json.dumps(self.valid_manifest()), encoding="utf-8")

            definition = load_conductor_manifest(path)

        self.assertEqual(definition.name, "Example Conductor")

    def test_invalid_runtime_specs_fail_clearly(self) -> None:
        raw = self.valid_manifest()
        raw["runtime"] = {"kind": "python", "module": "example.runtime"}
        with self.assertRaisesRegex(ConductorValidationError, "runtime.function"):
            validate_conductor_definition(raw)

        raw = self.valid_manifest()
        raw["runtime"] = {"kind": "command", "command": {"argv": []}}
        with self.assertRaisesRegex(ConductorValidationError, "runtime.command.argv"):
            validate_conductor_definition(raw)

        raw = self.valid_manifest()
        raw["runtime"] = {"kind": "sidecar"}
        with self.assertRaisesRegex(ConductorValidationError, "runtime.kind"):
            validate_conductor_definition(raw)

    def test_conductor_spec_reuses_performer_primitives(self) -> None:
        spec = ConductorSpec(
            id="example.code_first",
            name="Code First",
            runtime=RuntimeSpec(kind="command", command=CommandSpec(argv=("echo", "{brief}", "{video}"))),
            inputs=[PerformerPort("brief", "file")],
            outputs=[PerformerOutput("video", "file")],
            child_performers=["builtin.arrange"],
            cache={"mode": "none"},
        )

        definition = spec.to_definition()

        self.assertEqual(definition.inputs[0].name, "brief")
        self.assertEqual(definition.outputs[0].name, "video")
        self.assertEqual(definition.runtime.command.argv, ("echo", "{brief}", "{video}"))
        self.assertEqual(definition.child_performers, ("builtin.arrange",))

    def test_conductor_decorator_attaches_validated_definition(self) -> None:
        @conductor(
            id="example.decorated",
            name="Decorated",
            runtime={"kind": "python", "module": "example.decorated", "function": "run"},
            cache={"mode": "none"},
        )
        def run() -> None:
            return None

        self.assertEqual(run.conductor.id, "example.decorated")
        self.assertIs(run.conductor, run.CONDUCTOR)

    def test_package_root_exports_performer_primitives_for_conductors(self) -> None:
        self.assertIs(ExportedCommandSpec, CommandSpec)
        self.assertEqual(CachePolicy(mode="none").mode, "none")

    def test_performer_schema_remains_conductor_blind(self) -> None:
        performer = validate_performer_definition(
            {
                "id": "example.performer",
                "name": "Example Performer",
                "kind": "external",
                "version": "1.0",
                "command": {"argv": ["echo", "ok"]},
                "cache": {"mode": "none"},
            }
        )

        self.assertNotIn("child_conductors", performer.to_dict())
        self.assertFalse(hasattr(performer, "child_conductors"))


if __name__ == "__main__":
    unittest.main()
