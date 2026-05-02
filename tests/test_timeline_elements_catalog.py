import tempfile
import unittest
from pathlib import Path

from artagents.elements import catalog as effects_catalog
from artagents import timeline


class TimelineElementsCatalogTest(unittest.TestCase):
    def tearDown(self) -> None:
        effects_catalog.set_active_theme(None)

    def test_package_imported_timeline_uses_non_empty_element_catalogs(self) -> None:
        self.assertIn("text-card", effects_catalog.list_effect_ids())
        self.assertIn("fade-up", effects_catalog.list_animation_ids())
        self.assertIn("cross-fade", effects_catalog.list_transition_ids())

        config = {
            "theme": "banodoco-default",
            "tracks": [{"id": "v1", "kind": "visual", "label": "Visual"}],
            "clips": [
                {
                    "id": "a",
                    "at": 0,
                    "track": "v1",
                    "clipType": "text-card",
                    "hold": 1,
                    "params": {"content": "A", "entrance": "fade-up"},
                    "transition": {"id": "cross-fade", "durationFrames": 8},
                },
                {"id": "b", "at": 1, "track": "v1", "clipType": "text-card", "hold": 1, "params": {"content": "B"}},
            ],
        }

        timeline.validate_timeline(config)
        config["clips"][0]["params"]["entrance"] = "missing-animation"
        with self.assertRaisesRegex(ValueError, "animations catalog"):
            timeline.validate_timeline(config)

    def test_set_active_theme_preserves_theme_override_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            theme = Path(tmp) / "theme"
            root = theme / "effects" / "theme-only"
            root.mkdir(parents=True)
            (root / "component.tsx").write_text("export default function ThemeOnly() { return null; }\n", encoding="utf-8")
            (root / "schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
            (root / "defaults.json").write_text("{}\n", encoding="utf-8")
            (root / "meta.json").write_text('{"id":"theme-only","clipTypeAliases":["theme"]}\n', encoding="utf-8")

            effects_catalog.set_active_theme(theme)

            self.assertIn("theme-only", effects_catalog.list_effect_ids())
            self.assertEqual(effects_catalog.read_effect_meta("theme-only")["clipTypeAliases"], ["theme"])


if __name__ == "__main__":
    unittest.main()
