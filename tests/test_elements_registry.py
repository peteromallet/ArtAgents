import json
import tempfile
import unittest
from pathlib import Path

from astrid.core.element import ElementRegistryError, load_default_registry


_KIND_SINGULAR = {"effects": "effect", "animations": "animation", "transitions": "transition"}


def write_pack_element(
    pack_root: Path,
    kind: str,
    element_id: str,
    *,
    pack_id: str,
    label: str,
    js_packages: list[str] | None = None,
) -> Path:
    if not (pack_root / "pack.yaml").exists():
        pack_root.mkdir(parents=True, exist_ok=True)
        (pack_root / "pack.yaml").write_text(f"id: {pack_id}\nname: {pack_id}\nversion: 0.1.0\n", encoding="utf-8")
    element_root = pack_root / "elements" / kind / element_id
    element_root.mkdir(parents=True)
    (element_root / "component.tsx").write_text("export default function Element() { return null; }\n", encoding="utf-8")
    (element_root / "element.yaml").write_text(
        json.dumps(
            {
                "id": element_id,
                "kind": _KIND_SINGULAR[kind],
                "pack_id": pack_id,
                "metadata": {"label": label},
                "schema": {"type": "object"},
                "defaults": {"enabled": True},
                "dependencies": {
                    "js_packages": list(js_packages or []),
                    "python_requirements": [],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return element_root


def write_theme_element(theme_root: Path, kind: str, element_id: str, *, label: str) -> Path:
    element_root = theme_root / "elements" / kind / element_id
    element_root.mkdir(parents=True)
    (element_root / "component.tsx").write_text("export default function Element() { return null; }\n", encoding="utf-8")
    (element_root / "element.yaml").write_text(
        json.dumps(
            {
                "id": element_id,
                "kind": _KIND_SINGULAR[kind],
                "metadata": {"label": label},
                "schema": {"type": "object"},
                "defaults": {"enabled": True},
                "dependencies": {"js_packages": [], "python_requirements": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return element_root


class ElementRegistryTest(unittest.TestCase):
    def test_fade_animation_and_fade_transition_coexist_under_kind_keys(self) -> None:
        registry = load_default_registry()
        animation_fade = registry.get("animations", "fade")
        transition_fade = registry.get("transitions", "fade")
        self.assertEqual(animation_fade.kind, "animations")
        self.assertEqual(transition_fade.kind, "transitions")
        self.assertNotEqual(animation_fade.root, transition_fade.root)
        self.assertTrue(str(animation_fade.root).endswith("astrid/packs/builtin/elements/animations/fade"))
        self.assertTrue(str(transition_fade.root).endswith("astrid/packs/builtin/elements/transitions/fade"))

    def test_builtin_pack_defaults_are_discovered_with_pack_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            registry = load_default_registry(project_root=project)

            by_key = registry.as_mapping()

            self.assertIn(("effects", "text-card"), by_key)
            self.assertIn(("animations", "fade"), by_key)
            self.assertIn(("transitions", "cross-fade"), by_key)
            text_card = registry.get("effects", "text-card")
            self.assertEqual(text_card.source, "pack:builtin")
            self.assertFalse(text_card.editable)
            self.assertEqual(text_card.metadata["label"], "Text Card")
            self.assertEqual(text_card.metadata["pack_id"], "builtin")
            self.assertEqual(
                text_card.fork_target,
                Path("astrid/packs/local/elements/effects/text-card"),
            )

    def test_active_theme_overrides_builtin_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            theme = Path(tmp) / "theme"
            write_theme_element(theme, "effects", "text-card", label="Theme")

            registry = load_default_registry(active_theme=theme)

        winner = registry.get("effects", "text-card")
        self.assertEqual(winner.source, "active_theme")
        self.assertTrue(winner.editable)
        self.assertEqual(winner.metadata["label"], "Theme")
        conflicts = registry.conflicts()
        text_card_conflicts = [item for item in conflicts if item.kind == "effects" and item.id == "text-card"]
        self.assertEqual(len(text_card_conflicts), 1)
        self.assertEqual(
            [item.source for item in text_card_conflicts[0].shadowed],
            ["pack:builtin"],
        )

    def test_local_pack_wins_over_builtin_and_fork_target_uses_local_pack(self) -> None:
        from unittest import mock

        from astrid.core.element import registry as registry_module
        from astrid.core.pack import discover_packs as real_discover_packs

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir(parents=True)
            local_pack_root = project / "astrid" / "packs" / "local"
            write_pack_element(local_pack_root, "animations", "fade", pack_id="local", label="Local Fade")

            with mock.patch.object(
                registry_module,
                "discover_packs",
                side_effect=lambda root=None: real_discover_packs() + real_discover_packs(local_pack_root.parent),
            ):
                registry = load_default_registry(project_root=project)
                target = registry.fork_target("animations", "fade", project_root=project)

        winner = registry.get("animations", "fade")
        self.assertEqual(winner.source, "pack:local")
        self.assertTrue(winner.editable)
        self.assertEqual(target, project / "astrid" / "packs" / "local" / "elements" / "animations" / "fade")

    def test_fork_copies_default_into_local_pack_and_rewrites_pack_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir(parents=True)
            registry = load_default_registry(project_root=project)

            target = registry.fork("transitions", "cross-fade", project_root=project)

            self.assertTrue((target / "component.tsx").is_file())
            self.assertTrue((target / "element.yaml").is_file())
            payload = json.loads((target / "element.yaml").read_text(encoding="utf-8"))
            self.assertEqual(payload["pack_id"], "local")
            self.assertTrue((project / "astrid" / "packs" / "local" / "pack.yaml").is_file())
            with self.assertRaisesRegex(ElementRegistryError, "already exists"):
                registry.fork("transitions", "cross-fade", project_root=project)


if __name__ == "__main__":
    unittest.main()
