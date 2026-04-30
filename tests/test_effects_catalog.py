# extends prior plan Step 16
import json
import os
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

import effects_catalog


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "gen_effect_registry.py"
# Sprint 5: codegen output moved into the package source. The in-tree
# `tools/remotion/src/<kind>.generated.ts` files are now back-compat
# shims that re-export from the package.
WORKSPACE_ROOT = ROOT.parent
PACKAGE_SRC = WORKSPACE_ROOT / "packages" / "timeline-composition" / "typescript" / "src"
GENERATED = PACKAGE_SRC / "effects.generated.ts"
GENERATED_ANIMATIONS = PACKAGE_SRC / "animations.generated.ts"
GENERATED_TRANSITIONS = PACKAGE_SRC / "transitions.generated.ts"
GENERATED_SHIM = ROOT / "remotion" / "src" / "effects.generated.ts"
GENERATED_SHIM_ANIMATIONS = ROOT / "remotion" / "src" / "animations.generated.ts"
GENERATED_SHIM_TRANSITIONS = ROOT / "remotion" / "src" / "transitions.generated.ts"
ACTIVE_THEME_LINK = ROOT / "remotion" / "_active_theme"
ACTIVE_THEME_POINTER = ROOT / "remotion" / "_active_theme.txt"
THEME_FIXTURE = ROOT / "tests" / "fixtures" / "themes" / "_t"
GENERATED_FILES = (
    GENERATED,
    GENERATED_ANIMATIONS,
    GENERATED_TRANSITIONS,
    GENERATED_SHIM,
    GENERATED_SHIM_ANIMATIONS,
    GENERATED_SHIM_TRANSITIONS,
)

_GENERATOR_SPEC = importlib.util.spec_from_file_location("gen_effect_registry", GENERATOR)
assert _GENERATOR_SPEC is not None
gen_effect_registry = importlib.util.module_from_spec(_GENERATOR_SPEC)
assert _GENERATOR_SPEC.loader is not None
sys.modules[_GENERATOR_SPEC.name] = gen_effect_registry
_GENERATOR_SPEC.loader.exec_module(gen_effect_registry)


def _active_theme_target() -> str | None:
    if os.name == "nt" and ACTIVE_THEME_POINTER.exists():
        return ACTIVE_THEME_POINTER.read_text(encoding="utf-8").strip()
    if ACTIVE_THEME_LINK.is_symlink():
        return str(ACTIVE_THEME_LINK.resolve())
    if ACTIVE_THEME_POINTER.exists():
        return ACTIVE_THEME_POINTER.read_text(encoding="utf-8").strip()
    return None


class EffectsCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self._generated_before = {
            path: path.read_text(encoding="utf-8") if path.exists() else None
            for path in GENERATED_FILES
        }
        self._active_link_before = (
            ACTIVE_THEME_LINK.readlink() if ACTIVE_THEME_LINK.is_symlink() else None
        )
        self._active_pointer_before = (
            ACTIVE_THEME_POINTER.read_text(encoding="utf-8")
            if ACTIVE_THEME_POINTER.exists()
            else None
        )

    def tearDown(self) -> None:
        for path, content in self._generated_before.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(content, encoding="utf-8")

        if ACTIVE_THEME_LINK.is_symlink() or ACTIVE_THEME_LINK.is_file():
            ACTIVE_THEME_LINK.unlink()
        if ACTIVE_THEME_POINTER.exists():
            ACTIVE_THEME_POINTER.unlink()

        if self._active_link_before is not None:
            ACTIVE_THEME_LINK.symlink_to(self._active_link_before, target_is_directory=True)
        if self._active_pointer_before is not None:
            ACTIVE_THEME_POINTER.write_text(self._active_pointer_before, encoding="utf-8")

    def _run_generator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(GENERATOR), *args],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

    def test_catalog_reads_text_card_files(self) -> None:
        self.assertIn("text-card", effects_catalog.list_effect_ids())
        schema = effects_catalog.read_effect_schema("text-card")
        defaults = effects_catalog.read_effect_defaults("text-card")
        meta = effects_catalog.read_effect_meta("text-card")

        self.assertEqual(schema["required"], ["content"])
        self.assertEqual(defaults["align"], "center")
        self.assertEqual(meta["id"], "text-card")
        self.assertIn("whenToUse", meta)

    def test_generator_outputs_text_card_registry(self) -> None:
        self._run_generator()
        generated = GENERATED.read_text(encoding="utf-8")
        self.assertIn("EFFECT_IDS = ['text-card']", generated)
        self.assertIn("'text-card': TextCard", generated)
        self.assertIn("text: 'text-card'", generated)
        generated_animations = GENERATED_ANIMATIONS.read_text(encoding="utf-8")
        generated_transitions = GENERATED_TRANSITIONS.read_text(encoding="utf-8")
        self.assertIn("ANIMATION_IDS = ['fade', 'fade-up', 'scale-in', 'slide-left', 'slide-up', 'type-on']", generated_animations)
        self.assertIn("TRANSITION_IDS = ['cross-fade', 'fade']", generated_transitions)
        json.loads(json.dumps(schema := effects_catalog.read_effect_schema("text-card")))
        self.assertEqual(schema["properties"]["align"]["enum"], ["left", "center", "right"])

    def test_catalog_uses_same_contract_for_all_primitive_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            theme = workspace / "themes" / "brand"

            def write_plugin(kind: str, plugin_id: str, *, root: Path = workspace) -> None:
                plugin_root = root / kind / plugin_id
                plugin_root.mkdir(parents=True)
                (plugin_root / "component.tsx").write_text(
                    f"export default function {plugin_id.replace('-', '_')}() {{ return null; }}\n",
                    encoding="utf-8",
                )
                (plugin_root / "schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
                (plugin_root / "defaults.json").write_text('{"enabled":true}\n', encoding="utf-8")
                (plugin_root / "meta.json").write_text(
                    json.dumps({"id": plugin_id, "label": plugin_id}) + "\n",
                    encoding="utf-8",
                )

            write_plugin("effects", "stamp")
            write_plugin("animations", "fade-up")
            write_plugin("transitions", "crossfade")
            write_plugin("animations", "fade-up", root=theme)
            invalid = workspace / "transitions" / "missing-defaults"
            invalid.mkdir(parents=True)
            (invalid / "component.tsx").write_text("export default function Missing() {}\n", encoding="utf-8")
            (invalid / "schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
            (invalid / "meta.json").write_text('{"id":"missing-defaults"}\n', encoding="utf-8")

            old_workspace_root = effects_catalog.WORKSPACE_ROOT
            old_themes_root = effects_catalog.THEMES_ROOT
            old_active_theme = effects_catalog._ACTIVE_THEME_DIR
            try:
                effects_catalog.WORKSPACE_ROOT = workspace
                effects_catalog.THEMES_ROOT = workspace / "themes"
                effects_catalog.set_active_theme(None)

                self.assertEqual(effects_catalog.list_effect_ids(), ["stamp"])
                self.assertEqual(effects_catalog.list_animation_ids(), ["fade-up"])
                self.assertEqual(effects_catalog.list_transition_ids(), ["crossfade"])
                self.assertEqual(
                    effects_catalog.read_animation_defaults("fade-up"),
                    {"enabled": True},
                )
                self.assertEqual(
                    effects_catalog.read_transition_meta("crossfade")["id"],
                    "crossfade",
                )

                effects_catalog.set_active_theme(theme)
                self.assertEqual(effects_catalog.list_animation_ids(), ["fade-up"])
                self.assertEqual(
                    effects_catalog.read_animation_meta("fade-up")["label"],
                    "fade-up",
                )
            finally:
                effects_catalog.WORKSPACE_ROOT = old_workspace_root
                effects_catalog.THEMES_ROOT = old_themes_root
                effects_catalog._ACTIVE_THEME_DIR = old_active_theme

    def test_theme_effects_merge_with_workspace_effects(self) -> None:
        result = self._run_generator("--theme", str(THEME_FIXTURE))
        self.assertIn("overrides workspace effect 'text-card'", result.stderr)

        generated = GENERATED.read_text(encoding="utf-8")
        self.assertIn("'test-stamp'", generated)
        self.assertIn("'text-card'", generated)
        self.assertIn("import TestStamp from '@theme-effects/test-stamp/component';", generated)

        self._run_generator()
        generated_without_theme = GENERATED.read_text(encoding="utf-8")
        self.assertIn("'text-card'", generated_without_theme)
        self.assertNotIn("test-stamp", generated_without_theme)
        self.assertIn("ACTIVE_THEME_ID = null", generated_without_theme)
        self.assertIn("ACTIVE_THEME_ID = null", GENERATED_ANIMATIONS.read_text(encoding="utf-8"))
        self.assertIn("ACTIVE_THEME_ID = null", GENERATED_TRANSITIONS.read_text(encoding="utf-8"))

    def test_generator_builds_primitive_registries_with_workspace_and_theme_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            theme = workspace / "themes" / "brand"

            def write_plugin(kind: str, plugin_id: str, *, root: Path = workspace) -> None:
                plugin_root = root / kind / plugin_id
                plugin_root.mkdir(parents=True)
                defaults = {"enabled": True}
                meta: dict[str, object] = {"id": plugin_id, "clipTypeAliases": ["stamp-alias"]}
                if kind == "animations":
                    defaults = {"durationFrames": 12}
                    meta = {
                        "id": plugin_id,
                        "kind": "hook" if plugin_id == "type-on" else "wrapper",
                        "phase": "entrance",
                        "defaultDurationFrames": 12,
                    }
                elif kind == "transitions":
                    defaults = {"durationFrames": 9}
                    meta = {"id": plugin_id, "label": "Crossfade"}
                (plugin_root / "component.tsx").write_text(
                    f"export default function {plugin_id.replace('-', '_')}() {{ return null; }}\n",
                    encoding="utf-8",
                )
                (plugin_root / "schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
                (plugin_root / "defaults.json").write_text(json.dumps(defaults) + "\n", encoding="utf-8")
                (plugin_root / "meta.json").write_text(json.dumps(meta) + "\n", encoding="utf-8")

            write_plugin("effects", "stamp")
            write_plugin("animations", "fade-up")
            write_plugin("animations", "type-on", root=theme)
            write_plugin("transitions", "crossfade")
            write_plugin("transitions", "crossfade", root=theme)

            old_workspace_root = gen_effect_registry.WORKSPACE_ROOT
            old_themes_root = gen_effect_registry.THEMES_ROOT
            try:
                gen_effect_registry.WORKSPACE_ROOT = workspace
                gen_effect_registry.THEMES_ROOT = workspace / "themes"

                effects = gen_effect_registry.generate_primitive_registry("effects", theme_dir=theme)
                animations = gen_effect_registry.generate_primitive_registry("animations", theme_dir=theme)
                transitions = gen_effect_registry.generate_primitive_registry("transitions", theme_dir=theme)

                self.assertIn("import Stamp from '@workspace-effects/stamp/component';", effects)
                self.assertIn("EFFECT_IDS = ['stamp']", effects)
                self.assertIn("'stamp': Stamp", effects)
                self.assertIn("'stamp-alias': 'stamp'", effects)

                self.assertIn("import FadeUp from '@workspace-animations/fade-up/component';", animations)
                self.assertIn("import TypeOn from '@theme-animations/type-on/component';", animations)
                self.assertIn("ANIMATION_IDS = ['fade-up', 'type-on']", animations)
                self.assertIn("'fade-up': FadeUp", animations)
                self.assertIn("'type-on': TypeOn", animations)
                self.assertIn("'fade-up': {\"durationFrames\":12}", animations)
                self.assertIn("'type-on': {\"durationFrames\":12}", animations)
                self.assertIn("'fade-up': {\"defaultDurationFrames\":12,\"id\":\"fade-up\",\"kind\":\"wrapper\",\"phase\":\"entrance\"}", animations)
                self.assertIn("'type-on': {\"defaultDurationFrames\":12,\"id\":\"type-on\",\"kind\":\"hook\",\"phase\":\"entrance\"}", animations)

                self.assertIn("import Crossfade from '@theme-transitions/crossfade/component';", transitions)
                self.assertNotIn("@workspace-transitions/crossfade/component", transitions)
                self.assertIn("TRANSITION_IDS = ['crossfade']", transitions)
                self.assertIn("'crossfade': Crossfade", transitions)
                self.assertIn("'crossfade': {\"durationFrames\":9}", transitions)
                self.assertIn("'crossfade': {\"id\":\"crossfade\",\"label\":\"Crossfade\"}", transitions)
            finally:
                gen_effect_registry.WORKSPACE_ROOT = old_workspace_root
                gen_effect_registry.THEMES_ROOT = old_themes_root

    def test_theme_effect_collision_warns_and_theme_version_wins(self) -> None:
        result = self._run_generator("--theme", str(THEME_FIXTURE))
        self.assertIn(
            "WARN theme '_t' overrides workspace effect 'text-card'",
            result.stderr,
        )

        generated = GENERATED.read_text(encoding="utf-8")
        self.assertIn("import TextCard from '@theme-effects/text-card/component';", generated)
        self.assertNotIn("import TextCard from '@workspace-effects/text-card/component';", generated)

    def test_generator_is_idempotent_for_same_theme(self) -> None:
        self._run_generator("--theme", str(THEME_FIXTURE))
        first = GENERATED.read_bytes()
        first_target = _active_theme_target()

        self._run_generator("--theme", str(THEME_FIXTURE))
        second = GENERATED.read_bytes()
        second_target = _active_theme_target()

        self.assertEqual(first, second)
        self.assertEqual(str(THEME_FIXTURE.resolve()), first_target)
        self.assertEqual(first_target, second_target)


if __name__ == "__main__":
    unittest.main()
