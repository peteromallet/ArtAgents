from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents.core.element.registry import load_pack_elements
from artagents.core.executor.registry import ExecutorRegistry, load_default_registry as load_executor_registry, load_pack_executors
from artagents.core.orchestrator.registry import load_default_registry as load_orchestrator_registry, load_pack_orchestrators
from artagents.core.pack import PackValidationError, discover_packs, qualified_id_pack_id


def write_pack(root: Path, pack_id: str, *, folder: str | None = None) -> Path:
    pack_root = root / (folder or pack_id)
    pack_root.mkdir(parents=True)
    (pack_root / "pack.yaml").write_text(
        "\n".join(
            [
                f"id: {pack_id}",
                f"name: {pack_id.title()} Pack",
                "version: '1.0'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return pack_root


def write_executor(root: Path, folder: str, executor_id: str) -> Path:
    executor_root = root / folder
    executor_root.mkdir()
    kind = "external" if executor_id.startswith("external.") else "built_in"
    (executor_root / "executor.yaml").write_text(
        json.dumps(
            {
                "id": executor_id,
                "name": executor_id,
                "kind": kind,
                "version": "1.0",
                "command": {"argv": ["echo", executor_id]},
                "cache": {"mode": "none"},
            }
        ),
        encoding="utf-8",
    )
    return executor_root


def write_orchestrator(root: Path, folder: str, orchestrator_id: str) -> Path:
    orchestrator_root = root / folder
    orchestrator_root.mkdir()
    (orchestrator_root / "orchestrator.yaml").write_text(
        json.dumps(
            {
                "id": orchestrator_id,
                "name": orchestrator_id,
                "kind": "built_in",
                "version": "1.0",
                "runtime": {
                    "kind": "command",
                    "command": {"argv": ["echo", orchestrator_id]},
                },
            }
        ),
        encoding="utf-8",
    )
    return orchestrator_root


def write_element(root: Path, kind: str, element_id: str, *, pack_id: str) -> Path:
    element_root = root / "elements" / kind / element_id
    element_root.mkdir(parents=True)
    (element_root / "component.tsx").write_text("export default function Element() { return null; }\n", encoding="utf-8")
    (element_root / "schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
    (element_root / "defaults.json").write_text("{}\n", encoding="utf-8")
    (element_root / "meta.json").write_text(
        json.dumps({"id": element_id, "label": element_id, "pack_id": pack_id}) + "\n",
        encoding="utf-8",
    )
    return element_root


class PackDiscoveryTest(unittest.TestCase):
    def test_valid_pack_discovery_and_content_loaders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packs_root = Path(tmp) / "packs"
            pack_root = write_pack(packs_root, "builtin")
            write_executor(pack_root, "sample_executor", "builtin.sample_executor")
            write_orchestrator(pack_root, "sample_orchestrator", "builtin.sample_orchestrator")
            write_element(pack_root, "effects", "stamp", pack_id="builtin")

            packs = discover_packs(packs_root)
            self.assertEqual([pack.id for pack in packs], ["builtin"])

            with mock.patch("artagents.core.executor.registry.discover_packs", return_value=packs):
                executors = load_pack_executors()
            with mock.patch("artagents.core.orchestrator.registry.discover_packs", return_value=packs):
                orchestrators = load_pack_orchestrators()
            with mock.patch("artagents.core.element.registry.discover_packs", return_value=packs):
                elements = load_pack_elements()

        self.assertEqual([executor.id for executor in executors], ["builtin.sample_executor"])
        self.assertEqual(executors[0].metadata["pack_id"], "builtin")
        self.assertEqual(executors[0].metadata["source"], "pack")
        self.assertEqual([orchestrator.id for orchestrator in orchestrators], ["builtin.sample_orchestrator"])
        self.assertEqual(orchestrators[0].metadata["pack_id"], "builtin")
        self.assertEqual([(element.kind, element.id, element.source) for element in elements], [("effects", "stamp", "pack:builtin")])

    def test_default_registries_remain_populated_from_legacy_scans(self) -> None:
        executor_registry = load_executor_registry()
        orchestrator_registry = load_orchestrator_registry(executor_registry=executor_registry)

        self.assertEqual(len(executor_registry.list()), 34)
        self.assertGreaterEqual(len(orchestrator_registry.list()), 5)
        self.assertIn("builtin.cut", executor_registry.as_mapping())
        self.assertIn("external.moirae", executor_registry.as_mapping())
        self.assertIn("builtin.hype", orchestrator_registry.as_mapping())

    def test_duplicate_executor_id_in_pack_fails_registry_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = write_pack(Path(tmp) / "packs", "builtin")
            write_executor(pack_root, "first", "builtin.duplicate")
            write_executor(pack_root, "second", "builtin.duplicate")
            packs = discover_packs(Path(tmp) / "packs")

            with mock.patch("artagents.core.executor.registry.discover_packs", return_value=packs):
                with self.assertRaisesRegex(Exception, "duplicate executor id"):
                    ExecutorRegistry(load_pack_executors())

    def test_pack_folder_must_match_pack_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packs_root = Path(tmp) / "packs"
            write_pack(packs_root, "builtin", folder="external")

            with self.assertRaisesRegex(PackValidationError, "must match folder name"):
                discover_packs(packs_root)

    def test_misplaced_executor_id_fails_pack_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = write_pack(Path(tmp) / "packs", "builtin")
            write_executor(pack_root, "moirae", "external.moirae")
            packs = discover_packs(Path(tmp) / "packs")

            with mock.patch("artagents.core.executor.registry.discover_packs", return_value=packs):
                with self.assertRaisesRegex(PackValidationError, "found in pack 'builtin'"):
                    load_pack_executors()

    def test_misplaced_orchestrator_id_fails_pack_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = write_pack(Path(tmp) / "packs", "external")
            write_orchestrator(pack_root, "hype", "builtin.hype")
            packs = discover_packs(Path(tmp) / "packs")

            with mock.patch("artagents.core.orchestrator.registry.discover_packs", return_value=packs):
                with self.assertRaisesRegex(PackValidationError, "found in pack 'external'"):
                    load_pack_orchestrators()

    def test_misplaced_element_pack_id_fails_pack_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = write_pack(Path(tmp) / "packs", "builtin")
            write_element(pack_root, "effects", "stamp", pack_id="external")
            packs = discover_packs(Path(tmp) / "packs")

            with mock.patch("artagents.core.element.registry.discover_packs", return_value=packs):
                with self.assertRaisesRegex(PackValidationError, "declares pack_id 'external'"):
                    load_pack_elements()

    def test_qualified_id_pack_segment_helper_rejects_bare_ids(self) -> None:
        self.assertEqual(qualified_id_pack_id("builtin.cut"), "builtin")
        with self.assertRaisesRegex(PackValidationError, "must be qualified"):
            qualified_id_pack_id("cut")


if __name__ == "__main__":
    unittest.main()
