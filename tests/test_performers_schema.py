import ast
import json
import tempfile
import unittest
from pathlib import Path

from artagents.contracts import schema as contracts_schema
from artagents.performers import CommandSpec, PerformerOutput, PerformerPort, PerformerSpec, PerformerValidationError, load_performer_manifest, performer, validate_performer_definition
from artagents.performers import schema as performers_schema


class PerformerSchemaTest(unittest.TestCase):
    def valid_manifest(self) -> dict:
        return {
            "id": "example.performer",
            "name": "Example Performer",
            "kind": "external",
            "version": "1.0",
            "inputs": [{"name": "screenplay", "type": "file"}],
            "outputs": [{"name": "video", "type": "file", "mode": "create_or_replace", "placeholder": "output"}],
            "command": {
                "argv": ["{python_exec}", "-m", "example", "{screenplay}", "-o", "{output}"],
                "env": {"EXAMPLE_OUT": "{out}", "VIDEO_OUT": "{video}"},
            },
            "cache": {"mode": "sentinel", "sentinels": ["video.mp4"], "per_brief": True},
            "conditions": [{"kind": "requires_input", "input": "screenplay"}],
            "graph": {"depends_on": ["script"], "provides": ["video"]},
            "isolation": {"mode": "subprocess", "binaries": ["ffmpeg"], "network": False},
        }

    def test_valid_manifest_round_trips_to_stable_json(self) -> None:
        performer = validate_performer_definition(self.valid_manifest())

        self.assertEqual(performer.id, "example.performer")
        self.assertEqual(performer.outputs[0].placeholder, "output")
        encoded = performer.to_json()
        decoded = json.loads(encoded)
        self.assertEqual(decoded["command"]["argv"][-1], "{output}")
        self.assertEqual(decoded["command"]["env"]["VIDEO_OUT"], "{video}")
        self.assertEqual(decoded["outputs"][0]["mode"], "create_or_replace")

    def test_shared_contract_aliases_preserve_identity_and_shape(self) -> None:
        self.assertIs(CommandSpec, contracts_schema.CommandSpec)
        self.assertIs(performers_schema.CommandSpec, contracts_schema.CommandSpec)
        self.assertIs(PerformerPort, contracts_schema.PerformerPort)
        self.assertIs(performers_schema.PerformerPort, contracts_schema.PerformerPort)
        self.assertIs(PerformerOutput, contracts_schema.PerformerOutput)
        self.assertIs(performers_schema.PerformerOutput, contracts_schema.PerformerOutput)

        performer = validate_performer_definition(self.valid_manifest())

        self.assertEqual(
            performer.to_dict(),
            {
                "id": "example.performer",
                "name": "Example Performer",
                "kind": "external",
                "version": "1.0",
                "description": "",
                "inputs": [
                    {
                        "name": "screenplay",
                        "type": "file",
                        "required": True,
                        "description": "",
                    }
                ],
                "outputs": [
                    {
                        "name": "video",
                        "type": "file",
                        "mode": "create_or_replace",
                        "description": "",
                        "placeholder": "output",
                    }
                ],
                "command": {
                    "argv": ["{python_exec}", "-m", "example", "{screenplay}", "-o", "{output}"],
                    "env": {"EXAMPLE_OUT": "{out}", "VIDEO_OUT": "{video}"},
                },
                "cache": {
                    "mode": "sentinel",
                    "sentinels": ["video.mp4"],
                    "always_run": False,
                    "per_brief": True,
                },
                "conditions": [{"kind": "requires_input", "input": "screenplay"}],
                "graph": {"depends_on": ["script"], "provides": ["video"], "consumes": []},
                "isolation": {
                    "mode": "subprocess",
                    "requirements": [],
                    "binaries": ["ffmpeg"],
                    "network": False,
                },
                "metadata": {},
            },
        )

    def test_load_performer_manifest_reads_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "performer.json"
            path.write_text(json.dumps(self.valid_manifest()), encoding="utf-8")

            performer = load_performer_manifest(path)

        self.assertEqual(performer.name, "Example Performer")

    def test_missing_required_field_is_rejected(self) -> None:
        raw = self.valid_manifest()
        del raw["id"]

        with self.assertRaisesRegex(PerformerValidationError, "missing required field performer.id"):
            validate_performer_definition(raw)

    def test_invalid_output_mode_is_rejected(self) -> None:
        raw = self.valid_manifest()
        raw["outputs"][0]["mode"] = "replace_sometimes"

        with self.assertRaisesRegex(PerformerValidationError, "output 'video'.mode"):
            validate_performer_definition(raw)

    def test_bad_cache_policy_shape_is_rejected(self) -> None:
        raw = self.valid_manifest()
        raw["cache"] = {"mode": "sentinel", "sentinels": "video.mp4"}

        with self.assertRaisesRegex(PerformerValidationError, "performer.cache.sentinels must be a list"):
            validate_performer_definition(raw)

    def test_unknown_command_placeholder_is_rejected(self) -> None:
        raw = self.valid_manifest()
        raw["command"]["argv"].append("{missing_value}")

        with self.assertRaisesRegex(PerformerValidationError, r"unknown placeholder \{missing_value\}"):
            validate_performer_definition(raw)

    def test_runtime_placeholders_and_declared_output_placeholders_are_allowed(self) -> None:
        raw = self.valid_manifest()
        raw["command"]["cwd"] = "{brief_out}"
        raw["outputs"][0]["path_template"] = "{out}/{output}"

        performer = validate_performer_definition(raw)

        self.assertEqual(performer.command.cwd, "{brief_out}")

    def test_performer_spec_normalizes_through_existing_definition_schema(self) -> None:
        spec = PerformerSpec(
            id="example.code_first",
            name="Code First",
            inputs=[PerformerPort("screenplay", "file")],
            outputs=[PerformerOutput("video", "file", placeholder="output")],
            command=["{python_exec}", "-m", "example", "{screenplay}", "-o", "{output}"],
            cache={"mode": "none"},
            conditions=[{"kind": "requires_input", "input": "screenplay"}],
        )

        definition = spec.to_definition()

        self.assertEqual(definition.id, "example.code_first")
        self.assertEqual(definition.outputs[0].placeholder, "output")
        self.assertEqual(definition.command.argv[-1], "{output}")
        with self.assertRaisesRegex(PerformerValidationError, r"unknown placeholder \{missing\}"):
            PerformerSpec(
                id="example.bad_code_first",
                name="Bad Code First",
                command=["{missing}"],
            )

    def test_performer_decorator_attaches_validated_definition(self) -> None:
        @performer(
            id="example.decorated",
            name="Decorated",
            command=["{python_exec}", "--version"],
            cache={"mode": "none"},
        )
        def run() -> None:
            return None

        self.assertEqual(run.performer.id, "example.decorated")
        self.assertIs(run.performer, run.PERFORMER)

    def test_performer_schema_and_api_do_not_expose_conductor_concepts(self) -> None:
        for module in (performers_schema, __import__("artagents.performers.api", fromlist=["*"])):
            exported = set(getattr(module, "__all__", ()))
            self.assertFalse(any("Conductor" in name or "conductor" in name for name in exported))
            self.assertFalse(hasattr(module, "ConductorDefinition"))
            self.assertFalse(hasattr(module, "ConductorSpec"))

    def test_performer_definition_ignores_conductor_only_child_fields(self) -> None:
        raw = self.valid_manifest()
        raw["child_performers"] = ["builtin.transcribe"]
        raw["child_conductors"] = ["builtin.event_talks"]

        performer = validate_performer_definition(raw)

        self.assertNotIn("child_performers", performer.to_dict())
        self.assertNotIn("child_conductors", performer.to_dict())
        self.assertFalse(hasattr(performer, "child_performers"))
        self.assertFalse(hasattr(performer, "child_conductors"))

    def test_performer_schema_and_api_modules_do_not_import_conductors(self) -> None:
        offenders: list[str] = []
        for path in (Path("artagents/performers/schema.py"), Path("artagents/performers/api.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if _module_imports_conductors(tree):
                offenders.append(str(path))

        self.assertEqual(offenders, [])


def _module_imports_conductors(tree: ast.AST) -> bool:
    for performer in ast.walk(tree):
        if isinstance(performer, ast.Import):
            for alias in performer.names:
                if alias.name == "artagents.conductors" or alias.name.startswith("artagents.conductors."):
                    return True
        elif isinstance(performer, ast.ImportFrom):
            module = performer.module or ""
            if module == "artagents.conductors" or module.startswith("artagents.conductors."):
                return True
    return False


if __name__ == "__main__":
    unittest.main()
