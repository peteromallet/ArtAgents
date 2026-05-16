"""Verify shipped (non-builtin) executor and orchestrator ids live in matching packs."""

from __future__ import annotations

import unittest

from astrid.core.executor.registry import load_default_registry as load_executor_registry
from astrid.core.orchestrator.registry import load_default_registry as load_orchestrator_registry
from astrid.core.pack import qualified_id_pack_id


class ShippedPackAlignmentTest(unittest.TestCase):
    def test_every_shipped_executor_first_segment_matches_owning_pack(self) -> None:
        registry = load_executor_registry()
        for executor in registry.list():
            with self.subTest(executor_id=executor.id):
                source_pack = executor.metadata.get("source_pack")
                self.assertIsNotNone(
                    source_pack,
                    f"executor {executor.id!r} missing metadata.source_pack",
                )
                self.assertEqual(
                    qualified_id_pack_id(executor.id),
                    source_pack,
                    f"executor {executor.id!r} first segment does not match source_pack {source_pack!r}",
                )

    def test_every_shipped_orchestrator_first_segment_matches_owning_pack(self) -> None:
        registry = load_orchestrator_registry()
        for orchestrator in registry.list():
            with self.subTest(orchestrator_id=orchestrator.id):
                source_pack = orchestrator.metadata.get("source_pack")
                self.assertIsNotNone(
                    source_pack,
                    f"orchestrator {orchestrator.id!r} missing metadata.source_pack",
                )
                self.assertEqual(
                    qualified_id_pack_id(orchestrator.id),
                    source_pack,
                    f"orchestrator {orchestrator.id!r} first segment does not match source_pack {source_pack!r}",
                )

    def test_known_non_builtin_ids_resolve_to_their_packs(self) -> None:
        registry = load_executor_registry()
        cases = [
            ("external.moirae", "external"),
            ("external.vibecomfy.run", "external"),
            ("external.vibecomfy.validate", "external"),
            ("iteration.prepare", "iteration"),
            ("iteration.assemble", "iteration"),
            ("upload.youtube", "upload"),
        ]
        for executor_id, pack in cases:
            with self.subTest(executor_id=executor_id):
                executor = registry.get(executor_id)
                self.assertEqual(executor.metadata["source_pack"], pack)
                root = str(executor.metadata["executor_root"]).rstrip("/")
                tail = executor_id.split(".", 1)[1]
                slug_head = tail.split(".")[0]
                self.assertTrue(
                    root.endswith(f"astrid/packs/{pack}/{slug_head}")
                    or root.endswith(f"astrid/packs/{pack}/{tail}")
                    or root.endswith(f"astrid/packs/{pack}/executors/{slug_head}")
                    or root.endswith(f"astrid/packs/{pack}/executors/{tail}"),
                    f"executor_root for {executor_id} did not land under packs/{pack}/",
                )


if __name__ == "__main__":
    unittest.main()
