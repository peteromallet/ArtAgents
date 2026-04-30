import importlib.util
import json
import sys
import unittest
from pathlib import Path

from artagents import effects_catalog
from artagents import timeline


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
GENERATOR = ROOT / "scripts" / "gen_effect_registry.py"

_GENERATOR_SPEC = importlib.util.spec_from_file_location("gen_effect_registry_for_primitives", GENERATOR)
assert _GENERATOR_SPEC is not None
gen_effect_registry = importlib.util.module_from_spec(_GENERATOR_SPEC)
assert _GENERATOR_SPEC.loader is not None
sys.modules[_GENERATOR_SPEC.name] = gen_effect_registry
_GENERATOR_SPEC.loader.exec_module(gen_effect_registry)


class CompositionPrimitiveTest(unittest.TestCase):
    def _assert_animation_plugin(self, animation_id: str, kind: str) -> None:
        root = WORKSPACE / "animations" / animation_id
        for filename in ("component.tsx", "schema.json", "defaults.json", "meta.json"):
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
            root = WORKSPACE / "animations" / animation_id
            for filename in ("component.tsx", "schema.json", "defaults.json", "meta.json"):
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

    def test_2rp_theme_effects_and_primitive_registries_generate_together(self) -> None:
        theme_dir = WORKSPACE / "themes" / "2rp"
        effects = gen_effect_registry.generate_primitive_registry("effects", theme_dir=theme_dir)
        animations = gen_effect_registry.generate_primitive_registry("animations", theme_dir=theme_dir)
        transitions = gen_effect_registry.generate_primitive_registry("transitions", theme_dir=theme_dir)

        for effect_id in ("section-hook", "art-card", "resource-card", "cta-card"):
            self.assertIn(f"'{effect_id}'", effects)
            defaults = json.loads((theme_dir / "effects" / effect_id / "defaults.json").read_text(encoding="utf-8"))
            self.assertTrue(defaults.get("entrance"))

        self.assertIn("@workspace-animations/fade-up/component", animations)
        self.assertIn("@workspace-transitions/cross-fade/component", transitions)

    def test_hype_composition_preserves_absolute_sequence_path_with_transition_series(self) -> None:
        # Sprint 5: HypeComposition.tsx physically moved to
        # packages/timeline-composition/typescript/src/TimelineComposition.tsx
        # (and renamed). Source assertions still apply.
        package_src = WORKSPACE / "packages" / "timeline-composition" / "typescript" / "src"
        source = (package_src / "TimelineComposition.tsx").read_text(encoding="utf-8")
        self.assertIn("TransitionSeries", source)
        self.assertIn("from={Math.round(clip.at * fps)}", source)
        self.assertIn("clipsCanTransition", source)


if __name__ == "__main__":
    unittest.main()
