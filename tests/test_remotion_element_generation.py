import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "gen_effect_registry.py"

_SPEC = importlib.util.spec_from_file_location("gen_effect_registry_elements_test", GENERATOR)
assert _SPEC is not None
gen_effect_registry = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gen_effect_registry
assert _SPEC.loader is not None
_SPEC.loader.exec_module(gen_effect_registry)


class RemotionElementGenerationTest(unittest.TestCase):
    def test_generated_registries_use_element_scope_aliases(self) -> None:
        for kind in ("effects", "animations", "transitions"):
            generated = gen_effect_registry.generate_element_registry(kind)
            self.assertIn("./effects-types", generated)
            self.assertNotIn("./effects.types", generated)
            self.assertRegex(generated, r"@(pack-builtin|managed)-elements-")
            self.assertNotIn("@workspace-", generated)
            self.assertNotIn("primitive-root", generated)

    def test_remotion_alias_files_do_not_reference_workspace_element_aliases(self) -> None:
        # `@workspace-*` aliases must be resolvable by the bundler because
        # `@banodoco/timeline-composition`'s codegenned `animations.generated.ts`
        # imports them transitively from `<TimelineComposition>`. They are
        # registered in `webpack-alias.mjs` (smoke bundle) and `remotion.config.ts`
        # (npx remotion render). The invariant we still enforce: AA's own
        # generator and tsconfig must not reference them — those are orthogonal
        # compile/codegen surfaces.
        checked = [
            ROOT / "scripts" / "gen_effect_registry.py",
            ROOT / "remotion" / "tsconfig.json",
        ]
        for path in checked:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("@workspace-", text)
            self.assertNotIn("workspace-effects", text)
            self.assertNotIn("workspace-animations", text)
            self.assertNotIn("workspace-transitions", text)


if __name__ == "__main__":
    unittest.main()
