from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OnboardingDocsTest(unittest.TestCase):
    def read_docs(self) -> str:
        return "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in (
                "README.md",
                "AGENTS.md",
                "SKILL.md",
                "docs/architecture.md",
                "docs/creating-tools.md",
            )
        )

    def run_artagents(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "artagents", *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_onboarding_docs_name_canonical_terms_and_guardrails(self) -> None:
        text = self.read_docs()
        required = (
            "orchestrators",
            "executors",
            "elements",
            "git status --short",
            "python3 -m artagents doctor",
            "python3 -m artagents --help",
            "python3 -m artagents",
            "executable package gateway",
            "python3 -m artagents setup",
            ".artagents/elements/overrides",
            "python3 scripts/gen_effect_registry.py",
            "artagents/packs/external/moirae/STAGE.md",
            "artagents/packs/external/vibecomfy/STAGE.md",
            "artagents/orchestrators/<slug>/{orchestrator.yaml,STAGE.md,run.py}",
            "artagents/packs/<pack>/<slug>/{executor.yaml,STAGE.md,run.py}",
            "Top-level `artagents/*.py`",
            "examples/briefs/",
            "docs/creating-tools.md",
            "docs/templates/executor/",
            "docs/templates/orchestrator/",
            "docs/templates/element/",
            "Create an **executor**",
            "Create an **orchestrator**",
            "Create an **element**",
            "Do not chain pipeline internals by hand",
            "brief-generation executor",
            "hype.assets.json",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        forbidden = (
            "python3 pipeline.py",
            "pipeline.py remains",
            "python3 -m artagents conductors list",
            "python3 -m artagents performers list",
            "python3 -m artagents instruments list",
            "python3 -m artagents primitives list",
            "artagents/performers/curated",
            "artagents/conductors/curated",
            "Legacy public alias",
            "Compatibility aliases",
            "artagents/event_talks.py",
            "artagents/thumbnail_maker.py",
            "artagents/understand.py",
            "artagents/skills/reigh-data",
        )
        for phrase in forbidden:
            with self.subTest(forbidden=phrase):
                self.assertNotIn(phrase, text)

    def test_docs_visible_root_commands_are_dispatchable(self) -> None:
        commands = (
            ("doctor", "--json"),
            ("setup", "--json"),
            ("orchestrators", "list", "--json"),
            ("executors", "list", "--json"),
            ("elements", "list", "--json"),
        )
        for command in commands:
            with self.subTest(command=command):
                result = self.run_artagents(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.strip())

    def test_creation_templates_exist(self) -> None:
        required = (
            "docs/templates/executor/executor.yaml",
            "docs/templates/executor/run.py",
            "docs/templates/executor/STAGE.md",
            "docs/templates/orchestrator/orchestrator.yaml",
            "docs/templates/orchestrator/run.py",
            "docs/templates/orchestrator/STAGE.md",
            "docs/templates/element/component.tsx",
            "docs/templates/element/schema.json",
            "docs/templates/element/defaults.json",
            "docs/templates/element/meta.json",
        )
        for path in required:
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())


if __name__ == "__main__":
    unittest.main()
