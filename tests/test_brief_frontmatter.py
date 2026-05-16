"""Tests for brief frontmatter parsing (Phase 3 SD-003).

Covers ``parse_brief_frontmatter`` directly and the full ``pipeline.resolve_args
+ prepare_brief_artifacts`` flow that wires the parsed metadata into the
runtime fact set consumed by ``_initial_facts``. Verified precedence:
explicit ``--allow-generative-effects`` CLI flag wins, else the brief's
``allow_generative_visuals`` frontmatter value, else ``False``.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from astrid.packs.builtin.orchestrators.hype import run as pipeline
from astrid.packs.builtin.orchestrators.hype import run as hype_run


ROOT = Path(__file__).resolve().parents[1]


class ParseBriefFrontmatterTest(unittest.TestCase):
    """Direct coverage of the standalone parser helper."""

    def test_no_frontmatter_returns_text_unchanged(self) -> None:
        text = "This is just a brief.\nNo frontmatter here.\n"
        metadata, body = pipeline.parse_brief_frontmatter(text)
        self.assertEqual(metadata, {})
        self.assertEqual(body, text)

    def test_empty_brief_returns_empty(self) -> None:
        metadata, body = pipeline.parse_brief_frontmatter("")
        self.assertEqual(metadata, {})
        self.assertEqual(body, "")

    def test_parses_allow_generative_visuals_true(self) -> None:
        text = "---\nallow_generative_visuals: true\n---\nReal brief here.\n"
        metadata, body = pipeline.parse_brief_frontmatter(text)
        self.assertEqual(metadata, {"allow_generative_visuals": True})
        self.assertEqual(body, "Real brief here.\n")

    def test_parses_allow_generative_visuals_false(self) -> None:
        text = "---\nallow_generative_visuals: false\n---\nBody text.\n"
        metadata, body = pipeline.parse_brief_frontmatter(text)
        self.assertEqual(metadata, {"allow_generative_visuals": False})
        self.assertEqual(body, "Body text.\n")

    def test_unknown_keys_parsed_but_preserved(self) -> None:
        text = (
            "---\n"
            "allow_generative_visuals: true\n"
            "future_key: something\n"
            "tagline: \"keep generative\"\n"
            "---\n"
            "After.\n"
        )
        metadata, body = pipeline.parse_brief_frontmatter(text)
        self.assertEqual(metadata["allow_generative_visuals"], True)
        self.assertEqual(metadata["future_key"], "something")
        self.assertEqual(metadata["tagline"], "keep generative")
        self.assertEqual(body, "After.\n")

    def test_missing_closing_fence_returns_text_unchanged(self) -> None:
        text = "---\nallow_generative_visuals: true\nstill no closing fence\n"
        metadata, body = pipeline.parse_brief_frontmatter(text)
        self.assertEqual(metadata, {})
        self.assertEqual(body, text)

    def test_em_dash_separator_is_not_treated_as_frontmatter(self) -> None:
        # Brief that legitimately starts with --- but isn't frontmatter:
        # bail out cleanly so we don't eat the body.
        text = "--- a long em-dash separator ---\nNot frontmatter.\n"
        metadata, body = pipeline.parse_brief_frontmatter(text)
        self.assertEqual(metadata, {})
        self.assertEqual(body, text)

    def test_blank_and_comment_lines_inside_frontmatter(self) -> None:
        text = (
            "---\n"
            "# leading comment\n"
            "\n"
            "allow_generative_visuals: true\n"
            "---\n"
            "Body.\n"
        )
        metadata, body = pipeline.parse_brief_frontmatter(text)
        self.assertEqual(metadata, {"allow_generative_visuals": True})
        self.assertEqual(body, "Body.\n")


class BriefFrontmatterFactsTest(unittest.TestCase):
    """End-to-end: resolve_args + prepare_brief_artifacts -> _initial_facts."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="brief-frontmatter-tests-", dir=ROOT))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _seed(self, brief_text: str, *, with_video: bool = True) -> tuple[Path, Path, Path]:
        video = self.root / "main.mp4"
        video.write_bytes(b"video")
        brief = self.root / "brief.txt"
        brief.write_text(brief_text, encoding="utf-8")
        out_dir = self.root / "out"
        return video, brief, out_dir

    def _resolve(self, brief_text: str, extra: list[str] | None = None) -> object:
        video, brief, out_dir = self._seed(brief_text)
        argv = [
            "--video",
            str(video),
            "--brief",
            str(brief),
            "--out",
            str(out_dir),
            *(extra or []),
        ]
        args = pipeline.resolve_args(argv)
        hype_run.prepare_brief_artifacts(args)
        return args

    def test_brief_true_sets_fact_without_cli_flag(self) -> None:
        args = self._resolve(
            "---\nallow_generative_visuals: true\n---\nBody.\n"
        )
        self.assertTrue(getattr(args, "brief_allow_generative_visuals"))
        self.assertFalse(getattr(args, "allow_generative_effects"))
        facts = hype_run._initial_facts(args)
        self.assertIn("generative_visuals_enabled", facts)

    def test_brief_false_does_not_set_fact_even_with_video(self) -> None:
        args = self._resolve(
            "---\nallow_generative_visuals: false\n---\nBody.\n"
        )
        self.assertFalse(getattr(args, "brief_allow_generative_visuals"))
        self.assertFalse(getattr(args, "allow_generative_effects"))
        facts = hype_run._initial_facts(args)
        self.assertNotIn("generative_visuals_enabled", facts)

    def test_no_frontmatter_does_not_set_fact_with_video(self) -> None:
        # Pre-existing behavior: no frontmatter means no generative effects in
        # source-video mode. Regression guard for SD-003.
        args = self._resolve("Plain brief, no frontmatter.\n")
        self.assertFalse(getattr(args, "brief_allow_generative_visuals"))
        self.assertEqual(getattr(args, "brief_frontmatter"), {})
        facts = hype_run._initial_facts(args)
        self.assertNotIn("generative_visuals_enabled", facts)

    def test_cli_flag_overrides_brief_false(self) -> None:
        args = self._resolve(
            "---\nallow_generative_visuals: false\n---\nBody.\n",
            extra=["--allow-generative-effects"],
        )
        self.assertFalse(getattr(args, "brief_allow_generative_visuals"))
        self.assertTrue(getattr(args, "allow_generative_effects"))
        facts = hype_run._initial_facts(args)
        self.assertIn("generative_visuals_enabled", facts)

    def test_cli_flag_and_brief_true_both_enable(self) -> None:
        args = self._resolve(
            "---\nallow_generative_visuals: true\n---\nBody.\n",
            extra=["--allow-generative-effects"],
        )
        self.assertTrue(getattr(args, "brief_allow_generative_visuals"))
        self.assertTrue(getattr(args, "allow_generative_effects"))
        facts = hype_run._initial_facts(args)
        self.assertIn("generative_visuals_enabled", facts)

    def test_brief_copy_strips_frontmatter(self) -> None:
        text = (
            "---\nallow_generative_visuals: true\nfuture_key: 7\n---\nReal body line 1.\nReal body line 2.\n"
        )
        args = self._resolve(text)
        copy_text = args.brief_copy.read_text(encoding="utf-8")
        self.assertEqual(copy_text, "Real body line 1.\nReal body line 2.\n")
        self.assertNotIn("allow_generative_visuals", copy_text)
        self.assertNotIn("---", copy_text)

    def test_brief_copy_preserves_text_without_frontmatter(self) -> None:
        text = "No frontmatter brief.\nLine 2.\n"
        args = self._resolve(text)
        self.assertEqual(args.brief_copy.read_text(encoding="utf-8"), text)

    def test_arrange_step_passes_allow_generative_when_brief_true(self) -> None:
        # Even with --video set, a brief that opts in should propagate
        # --allow-generative-effects to the arrange executor.
        args = self._resolve(
            "---\nallow_generative_visuals: true\n---\nBody.\n"
        )
        steps = {step.name: step for step in hype_run.build_pool_steps()}
        cmd = steps["arrange"].build_cmd(args)
        self.assertIn("--allow-generative-effects", cmd)

    def test_arrange_step_omits_allow_generative_when_brief_false_and_video(self) -> None:
        args = self._resolve(
            "---\nallow_generative_visuals: false\n---\nBody.\n"
        )
        steps = {step.name: step for step in hype_run.build_pool_steps()}
        cmd = steps["arrange"].build_cmd(args)
        self.assertNotIn("--allow-generative-effects", cmd)


if __name__ == "__main__":
    unittest.main()
