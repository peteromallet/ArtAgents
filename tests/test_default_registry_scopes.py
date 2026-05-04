from __future__ import annotations

import unittest

from artagents.core.executor.registry import load_default_registry as load_executor_registry
from artagents.core.orchestrator.registry import load_default_registry as load_orchestrator_registry


class DefaultRegistryScopeTest(unittest.TestCase):
    def test_default_executor_registries_include_packs(self) -> None:
        canonical = load_executor_registry()
        canonical_ids = set(canonical.as_mapping())

        self.assertIn("builtin.render", canonical_ids)
        self.assertIn("upload.youtube", canonical_ids)
        self.assertIn("external.moirae", canonical_ids)
        self.assertIn("external.vibecomfy.run", canonical_ids)
        self.assertIn("external.vibecomfy.validate", canonical_ids)

        youtube = canonical.get("upload.youtube")
        self.assertEqual(youtube.metadata["source"], "pack")
        self.assertEqual(youtube.metadata["source_pack"], "upload")
        self.assertNotIn("pack_id", youtube.metadata)
        self.assertTrue(youtube.metadata["executor_root"].endswith("artagents/packs/upload/youtube"))
        self.assertTrue(youtube.metadata["manifest_file"].endswith("artagents/packs/upload/youtube/executor.yaml"))

        for executor_id, folder in (
            ("builtin.audio_understand", "audio_understand"),
            ("builtin.visual_understand", "visual_understand"),
            ("builtin.video_understand", "video_understand"),
        ):
            with self.subTest(executor_id=executor_id):
                action = canonical.get(executor_id)
                self.assertEqual(action.metadata["source"], "pack")
                self.assertEqual(action.metadata["source_pack"], "builtin")
                self.assertNotIn("pack_id", action.metadata)
                self.assertTrue(action.metadata["executor_root"].endswith(f"artagents/packs/builtin/{folder}"))
                self.assertTrue(action.metadata["manifest_file"].endswith(f"artagents/packs/builtin/{folder}/executor.yaml"))

        vibecomfy = canonical.get("external.vibecomfy.run")
        self.assertEqual(vibecomfy.kind, "external")
        self.assertEqual(vibecomfy.metadata["pack_id"], "vibecomfy")
        self.assertEqual(vibecomfy.metadata["source_pack"], "external")
        self.assertEqual(vibecomfy.metadata["source"], "pack")
        self.assertTrue(vibecomfy.metadata["executor_root"].endswith("artagents/packs/external/vibecomfy"))

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

    def test_canonical_builtin_executor_runtime_module(self) -> None:
        canonical = load_executor_registry()
        render = canonical.get("builtin.render")
        self.assertEqual(render.metadata["runtime_module"], "artagents.packs.builtin.render.run")

    def test_external_executor_roots_are_pack_native(self) -> None:
        registry = load_executor_registry()

        self.assertTrue(registry.get("external.moirae").metadata["executor_root"].endswith("artagents/packs/external/moirae"))
        self.assertTrue(
            registry.get("external.vibecomfy.run").metadata["executor_root"].endswith("artagents/packs/external/vibecomfy")
        )


if __name__ == "__main__":
    unittest.main()
