from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from astrid.core.element.registry import load_pack_elements
from astrid.core.executor.registry import ExecutorRegistry, load_default_registry as load_executor_registry, load_pack_executors
from astrid.core.orchestrator.registry import load_default_registry as load_orchestrator_registry, load_pack_orchestrators
from astrid.core.pack import PackResolver, PackValidationError, discover_packs, qualified_id_pack_id


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
    singular = {"effects": "effect", "animations": "animation", "transitions": "transition"}[kind]
    (element_root / "element.yaml").write_text(
        json.dumps(
            {
                "id": element_id,
                "kind": singular,
                "pack_id": pack_id,
                "metadata": {"label": element_id},
                "schema": {"type": "object"},
                "defaults": {},
                "dependencies": {"js_packages": [], "python_requirements": []},
            }
        )
        + "\n",
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

            resolver = PackResolver(packs_root)
            self.assertEqual([pack.id for pack in resolver.packs], ["builtin"])

            executors = load_pack_executors(resolver=resolver)
            orchestrators = load_pack_orchestrators(resolver=resolver)
            elements = load_pack_elements(resolver=resolver)

        self.assertEqual([executor.id for executor in executors], ["builtin.sample_executor"])
        self.assertEqual(executors[0].metadata["source_pack"], "builtin")
        self.assertEqual(executors[0].metadata["source"], "pack")
        self.assertEqual([orchestrator.id for orchestrator in orchestrators], ["builtin.sample_orchestrator"])
        self.assertEqual(orchestrators[0].metadata["source_pack"], "builtin")
        self.assertEqual([(element.kind, element.id, element.source) for element in elements], [("effects", "stamp", "pack:builtin")])

    def test_default_registries_remain_populated_from_legacy_scans(self) -> None:
        executor_registry = load_executor_registry()
        orchestrator_registry = load_orchestrator_registry(executor_registry=executor_registry)

        self.assertGreaterEqual(len(executor_registry.list()), 34)
        self.assertGreaterEqual(len(orchestrator_registry.list()), 5)
        self.assertIn("builtin.cut", executor_registry.as_mapping())
        self.assertIn("external.moirae", executor_registry.as_mapping())
        self.assertIn("builtin.hype", orchestrator_registry.as_mapping())

    def test_duplicate_executor_id_in_pack_fails_registry_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = write_pack(Path(tmp) / "packs", "builtin")
            write_executor(pack_root, "first", "builtin.duplicate")
            write_executor(pack_root, "second", "builtin.duplicate")
            resolver = PackResolver(Path(tmp) / "packs")

            with self.assertRaisesRegex(Exception, "duplicate executor id"):
                ExecutorRegistry(load_pack_executors(resolver=resolver))

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
            resolver = PackResolver(Path(tmp) / "packs")

            with self.assertRaisesRegex(PackValidationError, "found in pack 'builtin'"):
                load_pack_executors(resolver=resolver)

    def test_misplaced_orchestrator_id_fails_pack_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = write_pack(Path(tmp) / "packs", "external")
            write_orchestrator(pack_root, "hype", "builtin.hype")
            resolver = PackResolver(Path(tmp) / "packs")

            with self.assertRaisesRegex(PackValidationError, "found in pack 'external'"):
                load_pack_orchestrators(resolver=resolver)

    def test_misplaced_element_pack_id_fails_pack_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = write_pack(Path(tmp) / "packs", "builtin")
            write_element(pack_root, "effects", "stamp", pack_id="external")
            resolver = PackResolver(Path(tmp) / "packs")

            with self.assertRaisesRegex(PackValidationError, "declares pack_id 'external'"):
                load_pack_elements(resolver=resolver)

    def test_qualified_id_pack_segment_helper_rejects_bare_ids(self) -> None:
        self.assertEqual(qualified_id_pack_id("builtin.cut"), "builtin")
        with self.assertRaisesRegex(PackValidationError, "must be qualified"):
            qualified_id_pack_id("cut")

    # -- extra_pack_roots and .no-pack tests ---------------------------------

    def test_extra_pack_roots_merged_with_builtin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packs_root = Path(tmp) / "packs"
            extra_root = write_pack(packs_root, "extra_pack")
            write_executor(extra_root, "my_exec", "extra_pack.my_exec")

            # Create a resolver with the extra pack root merged
            resolver = PackResolver(packs_root)
            pack_ids = [p.id for p in resolver.packs]
            self.assertIn("extra_pack", pack_ids)

            executors = load_pack_executors(resolver=resolver)
            exec_ids = [e.id for e in executors]
            self.assertIn("extra_pack.my_exec", exec_ids)

    def test_no_pack_marker_skips_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packs_root = Path(tmp) / "packs"
            # Create a directory that looks like a pack but has .no-pack
            skip_dir = packs_root / "skip_me"
            skip_dir.mkdir(parents=True)
            (skip_dir / ".no-pack").write_text("")
            # Also put something that looks like pack contents
            (skip_dir / "executor.yaml").write_text("id: skip_me.test\n")

            # Create a valid pack alongside
            valid_dir = write_pack(packs_root, "valid")

            resolver = PackResolver(packs_root)
            pack_ids = [p.id for p in resolver.packs]
            self.assertIn("valid", pack_ids)
            self.assertNotIn("skip_me", pack_ids)

    def test_no_pack_marker_prevents_likely_pack_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packs_root = Path(tmp) / "packs"
            # Create a directory with executors/ that would trigger the
            # likely-pack heuristic — but with .no-pack it should be silent
            skip_dir = packs_root / "skip_me"
            skip_dir.mkdir(parents=True)
            (skip_dir / ".no-pack").write_text("")
            (skip_dir / "executors").mkdir()

            resolver = PackResolver(packs_root)
            # No findings about skip_me because .no-pack is present
            skip_findings = [f for f in resolver.findings if "skip_me" in f]
            self.assertEqual(skip_findings, [])

    def test_duplicate_pack_ids_across_extra_roots_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_a = Path(tmp) / "root_a"
            root_b = Path(tmp) / "root_b"
            write_pack(root_a, "dupe")
            write_pack(root_b, "dupe")

            with self.assertRaisesRegex(PackValidationError, "duplicate pack id"):
                PackResolver(root_a, root_b)

    def test_pack_resolver_findings_for_likely_pack_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packs_root = Path(tmp) / "packs"
            likely_dir = packs_root / "likely_pack"
            likely_dir.mkdir(parents=True)
            # Need an actual manifest in a subdirectory to trigger the heuristic
            exec_sub = likely_dir / "some_exec"
            exec_sub.mkdir(parents=True)
            (exec_sub / "executor.yaml").write_text("id: x.y\n")

            resolver = PackResolver(packs_root)
            findings = [f for f in resolver.findings if "likely_pack" in f]
            self.assertEqual(len(findings), 1)

    def test_declared_content_roots_used_over_rglob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            packs_root = Path(tmp) / "packs"
            pack_root = packs_root / "declared_pack"
            pack_root.mkdir(parents=True)
            (pack_root / "pack.yaml").write_text(
                "schema_version: 1\n"
                "id: declared_pack\n"
                "name: Declared Pack\n"
                "version: '1.0'\n"
                "content:\n"
                "  executors: my_executors\n"
                "  orchestrators: my_orchestrators\n",
                encoding="utf-8",
            )
            # Create an executor in the declared root
            exec_root = pack_root / "my_executors" / "my_exec"
            exec_root.mkdir(parents=True)
            (exec_root / "executor.yaml").write_text(
                json.dumps({
                    "id": "declared_pack.my_exec",
                    "name": "my_exec",
                    "kind": "built_in",
                    "version": "1.0",
                    "command": {"argv": ["echo", "hi"]},
                    "cache": {"mode": "none"},
                }),
                encoding="utf-8",
            )

            # Create a stray executor in the undeclared root (should be ignored)
            stray_root = pack_root / "executors" / "stray_exec"
            stray_root.mkdir(parents=True)
            (stray_root / "executor.yaml").write_text(
                json.dumps({
                    "id": "declared_pack.stray",
                    "name": "stray",
                    "kind": "built_in",
                    "version": "1.0",
                    "command": {"argv": ["echo", "stray"]},
                    "cache": {"mode": "none"},
                }),
                encoding="utf-8",
            )

            resolver = PackResolver(packs_root)
            pack = resolver.get_pack("declared_pack")
            self.assertEqual(pack.declared_content.get("executors"), "my_executors")

            executors = load_pack_executors(resolver=resolver)
            exec_ids = [e.id for e in executors]
            self.assertIn("declared_pack.my_exec", exec_ids)
            # The stray executor in an undeclared location should NOT be discovered
            self.assertNotIn("declared_pack.stray", exec_ids)


if __name__ == "__main__":
    unittest.main()
