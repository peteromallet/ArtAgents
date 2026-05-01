import json
import os
import tempfile
import unittest
from pathlib import Path

from artagents.performers.builtin import builtin_performers
from artagents.performers.folder import FolderPerformerError, discover_folder_performer_roots, load_folder_performer, load_folder_performers
from artagents.performers.registry import PerformerRegistry, PerformerRegistryError, load_default_registry
from artagents.performers.schema import PerformerValidationError, load_performer_manifest
from artagents.pipeline import STEP_ORDER


class PerformerRegistryTest(unittest.TestCase):
    def test_builtin_discovery_covers_step_order(self) -> None:
        performers = builtin_performers()

        self.assertEqual([performer.id for performer in performers], [f"builtin.{name}" for name in STEP_ORDER])

    def test_representative_builtin_metadata_is_typed(self) -> None:
        registry = load_default_registry()

        transcribe = registry.get("builtin.transcribe")
        self.assertEqual(transcribe.inputs[0].name, "audio")
        self.assertTrue(transcribe.inputs[0].required)
        self.assertEqual(transcribe.inputs[0].type, "file")

        arrange = registry.get("builtin.arrange")
        self.assertTrue(arrange.cache.per_brief)
        self.assertEqual(arrange.outputs[0].mode, "create_or_replace")

        pool_merge = registry.get("builtin.pool_merge")
        self.assertTrue(pool_merge.cache.always_run)
        self.assertEqual(pool_merge.outputs[0].mode, "mutate")

        refine = registry.get("builtin.refine")
        self.assertIn("mutate", {output.mode for output in refine.outputs})

        render = registry.get("builtin.render")
        self.assertEqual(render.outputs[0].name, "video")
        self.assertEqual(render.outputs[0].mode, "create_or_replace")

        validate = registry.get("builtin.validate")
        self.assertEqual(validate.outputs[0].name, "validation")

    def test_moirae_folder_performer_loads_with_output_placeholder(self) -> None:
        registry = load_default_registry()
        performer = registry.get("external.moirae")

        self.assertEqual(performer.id, "external.moirae")
        self.assertEqual(performer.inputs[0].name, "screenplay")
        self.assertTrue(performer.inputs[0].required)
        self.assertEqual(performer.outputs[0].name, "video")
        self.assertEqual(performer.outputs[0].placeholder, "output")
        self.assertIn("{output}", performer.command.argv)
        self.assertEqual(performer.isolation.requirements, ("moirae",))
        self.assertEqual(performer.isolation.binaries, ("asciinema", "agg", "ffmpeg"))
        self.assertFalse(performer.isolation.network)
        self.assertEqual(performer.metadata["homepage"], "https://github.com/peteromallet/Moirae")
        self.assertEqual(performer.metadata["source"], "folder")
        self.assertTrue(performer.metadata["performer_root"].endswith("artagents/performers/curated/moirae"))
        self.assertTrue(performer.metadata["requirements_file"].endswith("artagents/performers/curated/moirae/requirements.txt"))
        self.assertTrue(performer.metadata["skill_file"].endswith("artagents/performers/curated/moirae/SKILL.md"))
        self.assertFalse(Path("artagents/performers/curated/moirae.json").exists())
        self.assertEqual([item.id for item in registry.list()].count("external.moirae"), 1)

    def test_vibecomfy_folder_nodes_load_with_shared_package_metadata(self) -> None:
        registry = load_default_registry()
        run = registry.get("external.vibecomfy.run")
        validate = registry.get("external.vibecomfy.validate")

        self.assertEqual(run.metadata["package_id"], "vibecomfy")
        self.assertEqual(validate.metadata["package_id"], "vibecomfy")
        self.assertEqual(run.metadata["folder_id"], "vibecomfy")
        self.assertEqual(validate.metadata["folder_id"], "vibecomfy")
        self.assertTrue(run.metadata["performer_root"].endswith("artagents/performers/curated/vibecomfy"))
        self.assertTrue(run.metadata["requirements_file"].endswith("artagents/performers/curated/vibecomfy/requirements.txt"))
        self.assertTrue(run.metadata["skill_file"].endswith("artagents/performers/curated/vibecomfy/SKILL.md"))
        self.assertEqual(run.command.argv, ("{python_exec}", "-m", "vibecomfy.cli", "run", "{workflow}"))
        self.assertEqual(validate.command.argv, ("{python_exec}", "-m", "vibecomfy.cli", "validate", "{workflow}"))
        self.assertEqual(run.inputs[0].name, "workflow")
        self.assertEqual(validate.inputs[0].name, "workflow")

    def test_registry_rejects_duplicate_ids_and_bad_graph_references(self) -> None:
        registry = load_default_registry()

        with self.assertRaisesRegex(PerformerRegistryError, "duplicate performer id"):
            registry.register(registry.get("external.moirae"))

        bad = registry.get("external.moirae").to_dict()
        bad["id"] = "external.bad_dependency"
        bad["graph"] = {"depends_on": ["missing.performer"]}

        with self.assertRaisesRegex(PerformerRegistryError, "depends on unknown performer"):
            PerformerRegistry([bad]).validate_all()

    def test_invalid_manifest_failure_is_clear(self) -> None:
        raw = load_default_registry().get("external.moirae").to_dict()
        raw["outputs"][0]["mode"] = "replace_sometimes"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaisesRegex(PerformerValidationError, "output 'video'.mode"):
                load_performer_manifest(path)

    def test_legacy_json_manifest_can_still_be_registered(self) -> None:
        raw = {
            "id": "external.legacy_json",
            "name": "Legacy JSON",
            "kind": "external",
            "version": "1",
            "outputs": [{"name": "artifact", "type": "file"}],
            "command": {"argv": ["echo", "ok"]},
            "cache": {"mode": "none"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.json"
            path.write_text(json.dumps(raw), encoding="utf-8")

            performer = load_performer_manifest(path)
            registry = PerformerRegistry([performer])

        self.assertEqual(registry.get("external.legacy_json").outputs[0].name, "artifact")

    def test_folder_performer_discovery_extracts_metadata_out_of_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            performer_root = root / "curated" / "example"
            performer_root.mkdir(parents=True)
            (performer_root / "requirements.txt").write_text("example-package\n", encoding="utf-8")
            (performer_root / "SKILL.md").write_text("# Example\n", encoding="utf-8")
            leak_key = "ARTAGENTS_FOLDER_NODE_IMPORT_LEAK"
            os.environ.pop(leak_key, None)
            (performer_root / "performer.py").write_text(
                "\n".join(
                    [
                        "import os",
                        "from artagents.performers import PerformerOutput, PerformerPort, PerformerSpec",
                        f"os.environ[{leak_key!r}] = 'child-only'",
                        "performer = PerformerSpec(",
                        "    id='external.folder_example',",
                        "    name='Folder Example',",
                        "    inputs=[PerformerPort('screenplay', 'file')],",
                        "    outputs=[PerformerOutput('video', 'file', placeholder='output')],",
                        "    command=['{python_exec}', '-m', 'example', '{screenplay}', '-o', '{output}'],",
                        "    cache={'mode': 'none'},",
                        "    conditions=[{'kind': 'requires_input', 'input': 'screenplay'}],",
                        ")",
                    ]
                ),
                encoding="utf-8",
            )

            roots = discover_folder_performer_roots(root)
            performers = load_folder_performers(root)

        self.assertEqual(roots, (performer_root.resolve(),))
        self.assertEqual(len(performers), 1)
        self.assertEqual(performers[0].id, "external.folder_example")
        self.assertEqual(performers[0].metadata["source"], "folder")
        self.assertEqual(performers[0].metadata["performer_root"], str(performer_root.resolve()))
        self.assertEqual(performers[0].metadata["requirements_file"], str((performer_root / "requirements.txt").resolve()))
        self.assertEqual(performers[0].metadata["skill_file"], str((performer_root / "SKILL.md").resolve()))
        self.assertNotEqual(os.environ.get(leak_key), "child-only")

    def test_folder_performer_discovery_flattens_nodes_with_shared_package_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            performer_root = root / "curated" / "multi_package"
            performer_root.mkdir(parents=True)
            (performer_root / "requirements.txt").write_text("example-package\n", encoding="utf-8")
            (performer_root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
            (performer_root / "SKILL.md").write_text("# Multi Package\n", encoding="utf-8")
            (performer_root / "performer.py").write_text(
                "\n".join(
                    [
                        "from artagents.performers import PerformerSpec",
                        "PACKAGE_ID = 'shared-example'",
                        "PERFORMERS = [",
                        "    PerformerSpec(",
                        "        id='external.multi.alpha',",
                        "        name='Alpha',",
                        "        command=['echo', 'alpha'],",
                        "        cache={'mode': 'none'},",
                        "        metadata={'performer_specific': 'alpha'},",
                        "    ),",
                        "    PerformerSpec(",
                        "        id='external.multi.beta',",
                        "        name='Beta',",
                        "        command=['echo', 'beta'],",
                        "        cache={'mode': 'none'},",
                        "        metadata={'performer_specific': 'beta'},",
                        "    ),",
                        "]",
                    ]
                ),
                encoding="utf-8",
            )

            performers = load_folder_performers(root)

        self.assertEqual([performer.id for performer in performers], ["external.multi.alpha", "external.multi.beta"])
        for performer in performers:
            self.assertEqual(performer.metadata["source"], "folder")
            self.assertEqual(performer.metadata["performer_root"], str(performer_root.resolve()))
            self.assertEqual(performer.metadata["performer_file"], str((performer_root / "performer.py").resolve()))
            self.assertEqual(performer.metadata["folder_id"], "multi_package")
            self.assertEqual(performer.metadata["package_id"], "shared-example")
            self.assertEqual(performer.metadata["requirements_file"], str((performer_root / "requirements.txt").resolve()))
            self.assertEqual(performer.metadata["pyproject_file"], str((performer_root / "pyproject.toml").resolve()))
            self.assertEqual(performer.metadata["skill_file"], str((performer_root / "SKILL.md").resolve()))
        self.assertEqual(performers[0].metadata["performer_specific"], "alpha")
        self.assertEqual(performers[1].metadata["performer_specific"], "beta")

    def test_folder_performer_decorator_discovery_ignores_imported_decorator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            performer_root = Path(tmp) / "decorated"
            performer_root.mkdir()
            (performer_root / "performer.py").write_text(
                "\n".join(
                    [
                        "from artagents.performers import performer",
                        "",
                        "@performer(",
                        "    id='external.decorated.example',",
                        "    name='Decorated Example',",
                        "    command=['echo', 'decorated'],",
                        "    cache={'mode': 'none'},",
                        ")",
                        "def run():",
                        "    pass",
                    ]
                ),
                encoding="utf-8",
            )

            loaded = load_folder_performer(performer_root)

        self.assertEqual(loaded.id, "external.decorated.example")
        self.assertEqual(loaded.command.argv, ("echo", "decorated"))
        self.assertEqual(loaded.metadata["folder_id"], "decorated")

    def test_folder_performer_requires_top_level_node_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            performer_root = Path(tmp) / "missing_metadata"
            performer_root.mkdir()
            (performer_root / "performer.py").write_text("VALUE = 1\n", encoding="utf-8")

            with self.assertRaisesRegex(FolderPerformerError, "top-level performer or PERFORMER"):
                load_folder_performer(performer_root)


if __name__ == "__main__":
    unittest.main()
