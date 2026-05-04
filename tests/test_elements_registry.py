import json
import tempfile
import unittest
from pathlib import Path

from artagents.core.element import ElementRegistryError, load_default_registry


_KIND_SINGULAR = {"effects": "effect", "animations": "animation", "transitions": "transition"}


def write_element(root: Path, kind: str, element_id: str, *, label: str, js_packages: list[str] | None = None) -> Path:
    element_root = root / kind / element_id
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


class ElementRegistryTest(unittest.TestCase):
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
            self.assertEqual(text_card.fork_target, Path(".artagents/elements/overrides/effects/text-card"))

    def test_active_theme_overrides_builtin_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            theme = Path(tmp) / "theme"
            write_element(project / ".artagents" / "elements" / "managed", "effects", "text-card", label="Managed")
            write_element(project / ".artagents" / "elements" / "overrides", "effects", "text-card", label="Override")
            write_element(theme / "elements", "effects", "text-card", label="Theme")

            registry = load_default_registry(active_theme=theme, project_root=project)

        winner = registry.get("effects", "text-card")
        self.assertEqual(winner.source, "active_theme")
        self.assertTrue(winner.editable)
        self.assertEqual(winner.metadata["label"], "Theme")
        conflicts = registry.conflicts()
        text_card_conflicts = [item for item in conflicts if item.kind == "effects" and item.id == "text-card"]
        self.assertEqual(len(text_card_conflicts), 1)
        self.assertEqual(
            [item.source for item in text_card_conflicts[0].shadowed],
            ["overrides", "managed", "pack:builtin"],
        )

    def test_override_wins_without_active_theme_and_fork_target_uses_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            write_element(project / ".artagents" / "elements" / "managed", "animations", "fade", label="Managed Fade")
            write_element(project / ".artagents" / "elements" / "overrides", "animations", "fade", label="Override Fade")

            registry = load_default_registry(project_root=project)
            target = registry.fork_target("animations", "fade", project_root=project)

        winner = registry.get("animations", "fade")
        self.assertEqual(winner.source, "overrides")
        self.assertTrue(winner.editable)
        self.assertEqual(target, project / ".artagents" / "elements" / "overrides" / "animations" / "fade")

    def test_fork_copies_non_editable_default_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            registry = load_default_registry(project_root=project)

            target = registry.fork("transitions", "cross-fade", project_root=project)

            self.assertTrue((target / "component.tsx").is_file())
            with self.assertRaisesRegex(ElementRegistryError, "already exists"):
                registry.fork("transitions", "cross-fade", project_root=project)

    def test_dependencies_are_read_from_structured_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            write_element(
                project / ".artagents" / "elements" / "overrides",
                "effects",
                "needs-package",
                label="Needs Package",
                js_packages=["@remotion/transitions@latest"],
            )

            registry = load_default_registry(project_root=project)

        element = registry.get("effects", "needs-package")
        self.assertEqual(element.dependencies.js_packages, ("@remotion/transitions@latest",))


if __name__ == "__main__":
    unittest.main()
