from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents.executors.registry import (
    load_builtin_executors,
    load_bundled_executors,
    load_default_registry as load_executor_registry,
)
from artagents.orchestrators.registry import load_bundled_orchestrators, load_default_registry as load_orchestrator_registry


class DefaultRegistryScopeTest(unittest.TestCase):
    def test_default_executor_registries_include_builtins_and_external_folders(self) -> None:
        canonical = load_executor_registry()
        canonical_ids = set(canonical.as_mapping())

        self.assertIn("builtin.render", canonical_ids)
        self.assertIn("upload.youtube", canonical_ids)
        self.assertIn("external.moirae", canonical_ids)
        self.assertIn("external.vibecomfy.run", canonical_ids)
        self.assertIn("external.vibecomfy.validate", canonical_ids)

        youtube = canonical.get("upload.youtube")
        self.assertEqual(youtube.metadata["source"], "folder")
        self.assertTrue(youtube.metadata["executor_root"].endswith("artagents/executors/upload_youtube"))
        self.assertTrue(youtube.metadata["manifest_file"].endswith("artagents/executors/upload_youtube/executor.yaml"))

        for executor_id, folder in (
            ("builtin.audio_understand", "audio_understand"),
            ("builtin.visual_understand", "visual_understand"),
            ("builtin.video_understand", "video_understand"),
        ):
            with self.subTest(executor_id=executor_id):
                action = canonical.get(executor_id)
                self.assertEqual(action.metadata["source"], "folder")
                self.assertTrue(action.metadata["executor_root"].endswith(f"artagents/executors/{folder}"))
                self.assertTrue(action.metadata["manifest_file"].endswith(f"artagents/executors/{folder}/executor.yaml"))

        vibecomfy = canonical.get("external.vibecomfy.run")
        self.assertEqual(vibecomfy.kind, "external")
        self.assertEqual(vibecomfy.metadata["package_id"], "vibecomfy")
        self.assertEqual(vibecomfy.metadata["source"], "folder")
        self.assertTrue(vibecomfy.metadata["executor_root"].endswith("artagents/executors/vibecomfy"))

    def test_default_orchestrator_registries_do_not_classify_vibecomfy_as_orchestrator(self) -> None:
        canonical = load_orchestrator_registry(executor_registry=load_executor_registry())
        canonical_ids = set(canonical.as_mapping())

        self.assertIn("builtin.hype", canonical_ids)
        self.assertIn("builtin.event_talks", canonical_ids)
        self.assertIn("builtin.thumbnail_maker", canonical_ids)
        self.assertFalse(any("vibecomfy" in orchestrator_id for orchestrator_id in canonical_ids))
        self.assertFalse(any(orchestrator_id == "upload.youtube" for orchestrator_id in canonical_ids))
        with self.assertRaises(KeyError):
            canonical.get("external.vibecomfy.run")

    def test_canonical_builtin_executor_import_uses_executor_metadata(self) -> None:
        builtin = {executor.id: executor for executor in load_builtin_executors()}
        self.assertIn("builtin.render", builtin)
        self.assertEqual(builtin["builtin.render"].metadata["runtime_module"], "artagents.executors.render.run")

    def test_bundled_executor_root_is_supported_without_curated_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled_root = root / "bundled_executor"
            bundled_root.mkdir()
            (bundled_root / "executor.py").write_text(
                "\n".join(
                    [
                        "from artagents.executors.api import ExecutorSpec",
                        "executor = ExecutorSpec(",
                        "    id='external.bundled_executor',",
                        "    name='Bundled Executor',",
                        "    command=['echo', 'bundled'],",
                        "    cache={'mode': 'none'},",
                        ")",
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch("artagents.executors.registry._bundled_manifest_paths", return_value=()), mock.patch(
                "artagents.executors.registry._bundled_folder_roots", return_value=(bundled_root,)
            ):
                bundled = load_bundled_executors()

        self.assertEqual([executor.id for executor in bundled], ["external.bundled_executor"])
        self.assertEqual(bundled[0].metadata["source"], "folder")

    def test_bundled_executor_manifest_root_is_bootstrap_light(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled_root = root / "manifest_executor"
            bundled_root.mkdir()
            (bundled_root / "requirements.txt").write_text("example-package\n", encoding="utf-8")
            (bundled_root / "STAGE.md").write_text("# Example\n", encoding="utf-8")
            (bundled_root / "assets").mkdir()
            (bundled_root / "assets" / "asset.txt").write_text("asset\n", encoding="utf-8")
            (bundled_root / "guides").mkdir()
            (bundled_root / "guides" / "guide.md").write_text("# Guide\n", encoding="utf-8")
            (bundled_root / "runtime.py").write_text("raise RuntimeError('runtime should not import')\n", encoding="utf-8")
            (bundled_root / "executor.yaml").write_text(
                "\n".join(
                    [
                        "executors:",
                        "  - id: external.manifest.alpha",
                        "    name: Manifest Alpha",
                        "    kind: external",
                        "    version: '1.0'",
                        "    command:",
                        "      argv: [\"echo\", \"alpha\"]",
                        "    cache:",
                        "      mode: none",
                        "  - id: external.manifest.beta",
                        "    name: Manifest Beta",
                        "    kind: external",
                        "    version: '1.0'",
                        "    command:",
                        "      argv: [\"echo\", \"beta\"]",
                        "    cache:",
                        "      mode: none",
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch("artagents.executors.registry._bundled_manifest_paths", return_value=()), mock.patch(
                "artagents.executors.registry._bundled_folder_roots", return_value=(bundled_root,)
            ):
                bundled = load_bundled_executors()

        self.assertEqual([executor.id for executor in bundled], ["external.manifest.alpha", "external.manifest.beta"])
        for executor in bundled:
            metadata = executor.metadata
            self.assertEqual(metadata["source"], "folder")
            self.assertEqual(metadata["executor_root"], str(bundled_root.resolve()))
            self.assertEqual(metadata["manifest_file"], str((bundled_root / "executor.yaml").resolve()))
            self.assertEqual(metadata["requirements_file"], str((bundled_root / "requirements.txt").resolve()))
            self.assertEqual(metadata["stage_file"], str((bundled_root / "STAGE.md").resolve()))
            self.assertEqual(metadata["assets_dir"], str((bundled_root / "assets").resolve()))
            self.assertEqual(metadata["guides_dir"], str((bundled_root / "guides").resolve()))
            self.assertEqual(metadata["asset_files"], [str((bundled_root / "assets" / "asset.txt").resolve())])
            self.assertEqual(metadata["guide_files"], [str((bundled_root / "guides" / "guide.md").resolve())])

    def test_bundled_orchestrator_root_is_supported_without_curated_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled_root = root / "bundled_orchestrator"
            bundled_root.mkdir()
            (bundled_root / "orchestrator.py").write_text(
                "\n".join(
                    [
                        "from artagents.orchestrators import OrchestratorSpec",
                        "orchestrator = OrchestratorSpec(",
                        "    id='external.bundled_orchestrator',",
                        "    name='Bundled Orchestrator',",
                        "    runtime={'kind': 'python', 'module': 'example.runtime', 'function': 'run'},",
                        "    cache={'mode': 'none'},",
                        ")",
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch("artagents.orchestrators.registry._bundled_manifest_paths", return_value=()), mock.patch(
                "artagents.orchestrators.registry._bundled_folder_roots", return_value=(bundled_root,)
            ):
                bundled = load_bundled_orchestrators()

        self.assertEqual([orchestrator.id for orchestrator in bundled], ["external.bundled_orchestrator"])
        self.assertEqual(bundled[0].metadata["source"], "folder")

    def test_external_executor_roots_are_canonical(self) -> None:
        registry = load_executor_registry()

        self.assertTrue(registry.get("external.moirae").metadata["executor_root"].endswith("artagents/executors/moirae"))
        self.assertTrue(
            registry.get("external.vibecomfy.run").metadata["executor_root"].endswith("artagents/executors/vibecomfy")
        )


if __name__ == "__main__":
    unittest.main()
