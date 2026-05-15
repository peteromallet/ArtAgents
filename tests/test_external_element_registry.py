"""Tests for external (installed) elements in registry and codegen.

Proves:
1. Installed external elements appear in load_default_registry() output.
2. gen_effect_registry.generate_element_registry() includes installed elements
   in the generated TypeScript output (import statement + registry entry).
3. gen_effect_registry.main() (full render codegen path) produces valid
   TypeScript with the installed element wired in.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES_MEDIA = _REPO_ROOT / "examples" / "packs" / "media"


class TestExternalElementRegistry(unittest.TestCase):
    """Prove installed external elements appear in registry and codegen."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="test-ext-elem-reg-")
        self._astrid_home = Path(self._tmpdir) / "astrid_home"
        self._astrid_home.mkdir(parents=True, exist_ok=True)
        # Packages dir needed for gen_effect_registry's PACKAGE_SRC
        self._pkg_dir = Path(self._tmpdir) / "packages" / "timeline-composition" / "typescript" / "src"
        self._pkg_dir.mkdir(parents=True, exist_ok=True)
        # Save original ASTRID_HOME
        self._orig_astrid_home = os.environ.get("ASTRID_HOME")

    def tearDown(self) -> None:
        if self._orig_astrid_home is not None:
            os.environ["ASTRID_HOME"] = self._orig_astrid_home
        else:
            os.environ.pop("ASTRID_HOME", None)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _set_astrid_home(self) -> None:
        """Point ASTRID_HOME at our isolated directory."""
        os.environ["ASTRID_HOME"] = str(self._astrid_home)

    def _env(self) -> dict:
        """Environment dict for subprocess calls."""
        env = os.environ.copy()
        env["ASTRID_HOME"] = str(self._astrid_home)
        existing = env.get("PYTHONPATH", "")
        repo = str(_REPO_ROOT)
        env["PYTHONPATH"] = f"{repo}{os.pathsep}{existing}" if existing else repo
        return env

    def _install_media_pack(self) -> None:
        """Install the media example pack into the isolated ASTRID_HOME."""
        result = subprocess.run(
            [sys.executable, "-m", "astrid", "packs", "install",
             str(_EXAMPLES_MEDIA), "--yes"],
            capture_output=True, text=True,
            cwd=str(_REPO_ROOT),
            env=self._env(),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Install media pack failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

    def test_installed_element_appears_in_load_default_registry(self) -> None:
        """load_default_registry(include_installed=True) includes the
        installed media pack's project-title-card element."""
        self._install_media_pack()
        self._set_astrid_home()

        from astrid.core.element.registry import load_default_registry

        registry = load_default_registry(include_installed=True)
        elements = registry.list()
        element_ids = [e.id for e in elements]
        self.assertIn(
            "project-title-card", element_ids,
            f"Installed element 'project-title-card' should be in registry. "
            f"Found: {element_ids}"
        )
        # Also verify the element's metadata
        elem = registry.get("effects", "project-title-card")
        self.assertEqual(elem.metadata.get("label"), "Project Title Card")

    def test_installed_element_not_present_when_include_installed_false(self) -> None:
        """load_default_registry(include_installed=False) may or may not
        include installed pack's element depending on resolver construction.
        Primary validation is the positive case above."""
        self._install_media_pack()
        self._set_astrid_home()

        from astrid.core.element.registry import load_default_registry

        # include_installed=False should not merge installed roots
        registry = load_default_registry(include_installed=False)
        elements = registry.list()
        element_ids = [e.id for e in elements]
        # project-title-card is only in the installed pack, so should NOT appear
        self.assertNotIn(
            "project-title-card", element_ids,
            f"Installed element should NOT appear when include_installed=False. "
            f"Found: {element_ids}"
        )

    def test_gen_effect_registry_includes_installed_element(self) -> None:
        """generate_element_registry('effects') includes the installed
        project-title-card element's import statement and registry entry."""
        self._install_media_pack()
        self._set_astrid_home()

        from scripts.gen_effect_registry import generate_element_registry

        # Monkey-patch module-level constants to avoid writing to real repo
        import scripts.gen_effect_registry as gen_mod
        orig_package_src = gen_mod.PACKAGE_SRC
        orig_outputs = dict(gen_mod.OUTPUTS)
        orig_tools_dir = gen_mod.TOOLS_DIR
        try:
            gen_mod.PACKAGE_SRC = self._pkg_dir
            gen_mod.OUTPUTS = {
                "effects": self._pkg_dir / "effects.generated.ts",
                "animations": self._pkg_dir / "animations.generated.ts",
                "transitions": self._pkg_dir / "transitions.generated.ts",
            }
            gen_mod.TOOLS_DIR = _REPO_ROOT

            generated = generate_element_registry("effects")
        finally:
            gen_mod.PACKAGE_SRC = orig_package_src
            gen_mod.OUTPUTS = orig_outputs
            gen_mod.TOOLS_DIR = orig_tools_dir

        # The generated TypeScript should contain:
        # - An import statement for ProjectTitleCard
        self.assertIn(
            "import ProjectTitleCard from '",
            generated,
            f"Expected import statement for ProjectTitleCard in generated TS.\n"
            f"Generated:\n{generated[:2000]}"
        )
        # - A registry entry for project-title-card
        self.assertIn(
            "'project-title-card': ProjectTitleCard",
            generated,
            f"Expected registry entry for project-title-card in generated TS.\n"
            f"Generated:\n{generated[:2000]}"
        )
        # - The import path should reference the pack-media scope
        self.assertIn(
            "@pack-media-elements",
            generated,
            f"Expected import path containing '@pack-media-elements'.\n"
            f"Generated:\n{generated[:2000]}"
        )

    def test_render_path_main_generates_valid_ts_with_element(self) -> None:
        """Prove the full render codegen path: install media pack, run
        gen_effect_registry.main() with mocked outputs, verify generated
        TypeScript includes the project-title-card import and registry
        entry, and passes a basic syntactic validity check."""
        self._install_media_pack()
        self._set_astrid_home()

        from scripts.gen_effect_registry import main as gen_main

        import scripts.gen_effect_registry as gen_mod
        orig_package_src = gen_mod.PACKAGE_SRC
        orig_outputs = dict(gen_mod.OUTPUTS)
        orig_shim_outputs = dict(gen_mod.SHIM_OUTPUTS)
        orig_tools_dir = gen_mod.TOOLS_DIR
        try:
            gen_mod.PACKAGE_SRC = self._pkg_dir
            gen_mod.OUTPUTS = {
                "effects": self._pkg_dir / "effects.generated.ts",
                "animations": self._pkg_dir / "animations.generated.ts",
                "transitions": self._pkg_dir / "transitions.generated.ts",
            }
            # Redirect shim outputs to temp dir as well
            gen_mod.SHIM_OUTPUTS = {
                "effects": self._pkg_dir / "effects.generated.ts.shim",
                "animations": self._pkg_dir / "animations.generated.ts.shim",
                "transitions": self._pkg_dir / "transitions.generated.ts.shim",
            }
            gen_mod.TOOLS_DIR = _REPO_ROOT

            exit_code = gen_main([])
            self.assertEqual(exit_code, 0,
                             f"gen_effect_registry.main() exited with {exit_code}")
        finally:
            gen_mod.PACKAGE_SRC = orig_package_src
            gen_mod.OUTPUTS = orig_outputs
            gen_mod.SHIM_OUTPUTS = orig_shim_outputs
            gen_mod.TOOLS_DIR = orig_tools_dir

        # Read the generated effects registry
        effects_file = self._pkg_dir / "effects.generated.ts"
        self.assertTrue(effects_file.is_file(),
                        f"Expected {effects_file} to exist after main()")

        generated = effects_file.read_text(encoding="utf-8")

        # (c) Assert the exact import statement and registry entry
        expected_import = (
            "import ProjectTitleCard from "
            "'@pack-media-elements-effects/project-title-card/component'"
        )
        self.assertIn(
            expected_import,
            generated,
            f"Expected exact import statement in generated TS.\n"
            f"Generated:\n{generated[:2000]}"
        )

        expected_entry = "'project-title-card': ProjectTitleCard,"
        self.assertIn(
            expected_entry,
            generated,
            f"Expected registry entry in generated TS.\n"
            f"Generated:\n{generated[:2000]}"
        )

        # (d) Basic syntactic validity check
        lines = generated.strip().splitlines()
        # Verify file has content
        self.assertGreater(len(lines), 5,
                           f"Generated TS should have more than 5 lines, got {len(lines)}")
        # Verify it starts with DO NOT EDIT comment
        self.assertTrue(
            lines[0].startswith("// DO NOT EDIT"),
            f"First line should be 'DO NOT EDIT' comment, got: {lines[0]!r}"
        )
        # Verify imports come before registry
        import_lines = [i for i, l in enumerate(lines)
                        if l.startswith("import ")]
        registry_lines = [i for i, l in enumerate(lines)
                          if "REGISTRY" in l and "=" in l]
        if import_lines and registry_lines:
            self.assertTrue(
                all(i < registry_lines[0] for i in import_lines),
                "All imports must come before registry declaration"
            )
        # Verify the file has registry closing brace
        self.assertTrue(
            any("};" in l for l in lines),
            "Generated TS should contain closing '};' for registry object"
        )


if __name__ == "__main__":
    unittest.main()
