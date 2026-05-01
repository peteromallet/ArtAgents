import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artagents.conductors import (
    ConductorRegistry,
    ConductorRegistryError,
    load_builtin_conductors,
    load_curated_conductors,
    load_default_registry,
)
from artagents.performers.registry import load_default_registry as load_default_performer_registry


def conductor_manifest(conductor_id: str, *, child_performers: list[str] | None = None, child_conductors: list[str] | None = None) -> dict:
    return {
        "id": conductor_id,
        "name": conductor_id.replace(".", " ").title(),
        "kind": "external",
        "version": "1.0",
        "runtime": {"kind": "python", "module": "example.runtime", "function": "run"},
        "child_performers": list(child_performers or []),
        "child_conductors": list(child_conductors or []),
        "cache": {"mode": "none"},
    }


class ConductorRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.performer_registry = load_default_performer_registry()

    def test_registration_lookup_listing_and_json_export(self) -> None:
        registry = ConductorRegistry(
            [
                conductor_manifest("external.beta", child_performers=["builtin.cut"]),
                conductor_manifest("external.alpha", child_performers=["builtin.transcribe"]),
                {**conductor_manifest("built_in.gamma"), "kind": "built_in"},
            ],
            performer_registry=self.performer_registry,
        )

        registry.validate_all()

        self.assertEqual(registry.get("external.alpha").child_performers, ("builtin.transcribe",))
        self.assertEqual([item.id for item in registry.list()], ["built_in.gamma", "external.alpha", "external.beta"])
        self.assertEqual([item.id for item in registry.list(kind="external")], ["external.alpha", "external.beta"])
        exported = registry.to_dict(kind="built_in")
        self.assertEqual([item["id"] for item in exported["conductors"]], ["built_in.gamma"])
        self.assertEqual(json.loads(registry.to_json(kind="built_in"))["conductors"][0]["id"], "built_in.gamma")
        self.assertIn("external.alpha", registry.as_mapping())

    def test_invalid_kind_filter_is_rejected(self) -> None:
        registry = ConductorRegistry(performer_registry=self.performer_registry)

        with self.assertRaisesRegex(ConductorRegistryError, "kind must be"):
            registry.list(kind="custom")

    def test_duplicate_ids_are_rejected_at_registration(self) -> None:
        registry = ConductorRegistry([conductor_manifest("external.duplicate")], performer_registry=self.performer_registry)

        with self.assertRaisesRegex(ConductorRegistryError, "duplicate conductor id"):
            registry.register(conductor_manifest("external.duplicate"))

    def test_unknown_child_performer_is_rejected(self) -> None:
        registry = ConductorRegistry(
            [conductor_manifest("external.bad_performer", child_performers=["builtin.missing"])],
            performer_registry=self.performer_registry,
        )

        with self.assertRaisesRegex(ConductorRegistryError, "unknown child performer"):
            registry.validate_all()

    def test_unknown_child_conductor_is_rejected(self) -> None:
        registry = ConductorRegistry(
            [conductor_manifest("external.parent", child_conductors=["external.missing"])],
            performer_registry=self.performer_registry,
        )

        with self.assertRaisesRegex(ConductorRegistryError, "unknown child conductor"):
            registry.validate_all()

    def test_declared_child_performers_and_child_conductors_validate(self) -> None:
        registry = ConductorRegistry(
            [
                conductor_manifest("external.child", child_performers=["builtin.transcribe"]),
                conductor_manifest(
                    "external.parent",
                    child_performers=["builtin.arrange"],
                    child_conductors=["external.child"],
                ),
            ],
            performer_registry=self.performer_registry,
        )

        validated = registry.validate_all()

        self.assertEqual([item.id for item in validated], ["external.child", "external.parent"])
        self.assertEqual(registry.get("external.parent").child_conductors, ("external.child",))
        self.assertEqual(registry.get("external.parent").child_performers, ("builtin.arrange",))

    def test_direct_self_reference_is_rejected(self) -> None:
        registry = ConductorRegistry(
            [conductor_manifest("external.self", child_conductors=["external.self"])],
            performer_registry=self.performer_registry,
        )

        with self.assertRaisesRegex(ConductorRegistryError, "cannot reference itself"):
            registry.validate_all()

    def test_indirect_cycle_is_rejected(self) -> None:
        registry = ConductorRegistry(
            [
                conductor_manifest("external.alpha", child_conductors=["external.beta"]),
                conductor_manifest("external.beta", child_conductors=["external.gamma"]),
                conductor_manifest("external.gamma", child_conductors=["external.alpha"]),
            ],
            performer_registry=self.performer_registry,
        )

        with self.assertRaisesRegex(ConductorRegistryError, "conductor cycle detected"):
            registry.validate_all()

    def test_curated_folder_conductors_load_through_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conductor_root = root / "example"
            conductor_root.mkdir()
            (conductor_root / "conductor.py").write_text(
                "\n".join(
                    [
                        "from artagents.conductors import ConductorSpec",
                        "conductor = ConductorSpec(",
                        "    id='external.curated_example',",
                        "    name='Curated Example',",
                        "    runtime={'kind': 'python', 'module': 'example.runtime', 'function': 'run'},",
                        "    child_performers=['builtin.transcribe'],",
                        "    cache={'mode': 'none'},",
                        ")",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("artagents.conductors.registry._curated_manifest_paths", return_value=()), patch(
                "artagents.conductors.registry._curated_folder_roots", return_value=(conductor_root,)
            ):
                curated = load_curated_conductors()
                registry = load_default_registry(performer_registry=self.performer_registry)

        self.assertEqual([item.id for item in curated], ["external.curated_example"])
        self.assertEqual(registry.get("external.curated_example").metadata["folder_id"], "example")

    def test_builtin_conductors_load_with_source_metadata(self) -> None:
        conductors = load_builtin_conductors()

        self.assertEqual([item.id for item in conductors], ["builtin.hype", "builtin.event_talks", "builtin.thumbnail_maker"])
        by_id = {item.id: item for item in conductors}
        self.assertEqual(by_id["builtin.hype"].metadata["source"], "built_in")
        self.assertEqual(by_id["builtin.hype"].metadata["legacy_entrypoint"], "pipeline.py")
        self.assertEqual(by_id["builtin.event_talks"].metadata["source"], "built_in")
        self.assertEqual(by_id["builtin.event_talks"].metadata["legacy_entrypoint"], "event_talks.py")
        self.assertEqual(by_id["builtin.thumbnail_maker"].metadata["source"], "built_in")
        self.assertEqual(by_id["builtin.thumbnail_maker"].metadata["legacy_entrypoint"], "thumbnail_maker.py")

    def test_curated_discovery_filters_builtin_owned_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builtin_root = root / "builtin"
            external_root = root / "external"
            builtin_root.mkdir()
            external_root.mkdir()
            (builtin_root / "conductor.py").write_text(
                "\n".join(
                    [
                        "from artagents.conductors import ConductorSpec",
                        "conductor = ConductorSpec(",
                        "    id='builtin.curated_duplicate',",
                        "    name='Curated Duplicate',",
                        "    kind='built_in',",
                        "    runtime={'kind': 'python', 'module': 'example.runtime', 'function': 'run'},",
                        "    cache={'mode': 'none'},",
                        ")",
                    ]
                ),
                encoding="utf-8",
            )
            (external_root / "conductor.py").write_text(
                "\n".join(
                    [
                        "from artagents.conductors import ConductorSpec",
                        "conductor = ConductorSpec(",
                        "    id='external.curated_owner',",
                        "    name='Curated Owner',",
                        "    runtime={'kind': 'python', 'module': 'example.runtime', 'function': 'run'},",
                        "    cache={'mode': 'none'},",
                        ")",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("artagents.conductors.registry._curated_manifest_paths", return_value=()), patch(
                "artagents.conductors.registry._curated_folder_roots", return_value=(builtin_root, external_root)
            ):
                curated = load_curated_conductors()

        self.assertEqual([item.id for item in curated], ["external.curated_owner"])
        self.assertEqual(curated[0].metadata["source"], "folder")

    def test_default_registry_loads_builtin_conductors_once(self) -> None:
        registry = load_default_registry(performer_registry=self.performer_registry)

        self.assertEqual([item.id for item in registry.list()], ["builtin.event_talks", "builtin.hype", "builtin.thumbnail_maker"])
        self.assertEqual(len(registry.as_mapping()), len({item.id for item in registry.list()}))
        self.assertEqual(registry.get("builtin.hype").metadata["source"], "built_in")
        self.assertEqual(registry.get("builtin.event_talks").metadata["source"], "built_in")
        self.assertEqual(registry.get("builtin.thumbnail_maker").metadata["source"], "built_in")


if __name__ == "__main__":
    unittest.main()
