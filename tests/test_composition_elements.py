import importlib.util
import sys
import unittest
from pathlib import Path

from astrid.core.element import catalog as effects_catalog
from astrid import timeline


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
GENERATOR = ROOT / "scripts" / "gen_effect_registry.py"

_GENERATOR_SPEC = importlib.util.spec_from_file_location("gen_effect_registry_for_elements", GENERATOR)
assert _GENERATOR_SPEC is not None
gen_effect_registry = importlib.util.module_from_spec(_GENERATOR_SPEC)
assert _GENERATOR_SPEC.loader is not None
sys.modules[_GENERATOR_SPEC.name] = gen_effect_registry
_GENERATOR_SPEC.loader.exec_module(gen_effect_registry)


class CompositionElementTest(unittest.TestCase):
    def _assert_animation_plugin(self, animation_id: str, kind: str) -> None:
        root = ROOT / "astrid" / "packs" / "builtin" / "elements" / "animations" / animation_id
        for filename in ("component.tsx", "element.yaml"):
            self.assertTrue((root / filename).is_file(), f"{root / filename} missing")
        self.assertEqual(effects_catalog.read_animation_meta(animation_id)["kind"], kind)
        self.assertIn("durationFrames", effects_catalog.read_animation_defaults(animation_id))

    def test_fade_animation_plugin_contract(self) -> None:
        self._assert_animation_plugin("fade", "wrapper")

    def test_fade_up_animation_plugin_contract(self) -> None:
        self._assert_animation_plugin("fade-up", "wrapper")

    def test_scale_in_animation_plugin_contract(self) -> None:
        self._assert_animation_plugin("scale-in", "wrapper")

    def test_slide_left_animation_plugin_contract(self) -> None:
        self._assert_animation_plugin("slide-left", "wrapper")

    def test_slide_up_animation_plugin_contract(self) -> None:
        self._assert_animation_plugin("slide-up", "wrapper")

    def test_type_on_animation_plugin_contract(self) -> None:
        self._assert_animation_plugin("type-on", "hook")

    def test_workspace_animation_plugins_have_runtime_contract_files(self) -> None:
        expected = {
            "fade": "wrapper",
            "fade-up": "wrapper",
            "scale-in": "wrapper",
            "slide-left": "wrapper",
            "slide-up": "wrapper",
            "type-on": "hook",
        }
        self.assertEqual(set(expected), set(effects_catalog.list_animation_ids()))
        for animation_id, kind in expected.items():
            root = ROOT / "astrid" / "packs" / "builtin" / "elements" / "animations" / animation_id
            for filename in ("component.tsx", "element.yaml"):
                self.assertTrue((root / filename).is_file(), f"{root / filename} missing")
            self.assertEqual(effects_catalog.read_animation_meta(animation_id)["kind"], kind)

    def test_transition_plugin_is_discoverable_and_validated(self) -> None:
        self.assertIn("cross-fade", effects_catalog.list_transition_ids())
        config = {
            "theme": "banodoco-default",
            "tracks": [{"id": "v1", "kind": "visual", "label": "Visual"}],
            "clips": [
                {"id": "a", "at": 0, "track": "v1", "clipType": "text-card", "hold": 1, "params": {"content": "A"}, "transition": {"id": "cross-fade", "durationFrames": 8}},
                {"id": "b", "at": 1, "track": "v1", "clipType": "text-card", "hold": 1, "params": {"content": "B"}},
            ],
        }
        timeline.validate_timeline(config)
        config["clips"][0]["transition"] = {"id": "missing-transition", "durationFrames": 8}
        with self.assertRaisesRegex(ValueError, "transitions catalog"):
            timeline.validate_timeline(config)

    def test_bundled_element_registries_generate_together(self) -> None:
        effects = gen_effect_registry.generate_element_registry("effects")
        animations = gen_effect_registry.generate_element_registry("animations")
        transitions = gen_effect_registry.generate_element_registry("transitions")

        self.assertIn("'text-card'", effects)
        self.assertRegex(effects, r"@pack-builtin-elements-effects/text-card/component")
        self.assertRegex(animations, r"@pack-builtin-elements-animations/fade-up/component")
        self.assertRegex(transitions, r"@pack-builtin-elements-transitions/cross-fade/component")

    def test_hype_composition_preserves_absolute_sequence_path_with_transition_series(self) -> None:
        # Sprint 5: HypeComposition.tsx physically moved to
        # packages/timeline-composition/typescript/src/TimelineComposition.tsx
        # (and renamed). Source assertions still apply.
        package_src = WORKSPACE / "packages" / "timeline-composition" / "typescript" / "src"
        source = (package_src / "TimelineComposition.tsx").read_text(encoding="utf-8")
        self.assertIn("TimelineCompositionProps", source)
        self.assertIn("getTimelineDurationInFrames", source)
        self.assertIn("export default TimelineComposition", source)


if __name__ == "__main__":
    unittest.main()
