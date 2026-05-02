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

    def run_pipeline(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "pipeline.py"), *args],
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
            "python3 pipeline.py doctor",
            "python3 pipeline.py --help",
            "python3 -m artagents --help",
            "python3 -m artagents",
            "executable package gateway",
            "python3 pipeline.py setup",
            "single command gateway",
            ".artagents/elements/overrides",
            "python3 scripts/gen_effect_registry.py",
            "artagents/executors/moirae/SKILL.md",
            "artagents/executors/vibecomfy/SKILL.md",
            "artagents/orchestrators/<slug>/{orchestrator.yaml,SKILL.md,run.py}",
            "artagents/executors/<slug>/{executor.yaml,SKILL.md,run.py}",
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
            "python3 pipeline.py conductors list",
            "python3 pipeline.py performers list",
            "python3 pipeline.py instruments list",
            "python3 pipeline.py primitives list",
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
                result = self.run_pipeline(*command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.strip())

    def test_creation_templates_exist(self) -> None:
        required = (
            "docs/templates/executor/executor.yaml",
            "docs/templates/executor/run.py",
            "docs/templates/executor/SKILL.md",
            "docs/templates/orchestrator/orchestrator.yaml",
            "docs/templates/orchestrator/run.py",
            "docs/templates/orchestrator/SKILL.md",
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
