"""Phase 3 mixed-mode regression test.

Proves that the pre-Phase-3 cut-step rejection of mixed source-video + generative
pools is gone, and that the Timeline class' runtime clip classification handles
mixed timelines without persisting a `kind` field (Reigh allowlist is closed).
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import unittest
from pathlib import Path

from artagents import timeline as timeline_mod
from artagents.executors.cut import run as cut
from artagents.executors.pool_merge import run as pool_merge
from artagents.timeline import ClipClassifiedKind, Timeline


class MixedModeCutTest(unittest.TestCase):
    def _tempdir(self) -> Path:
        tmp = tempfile.TemporaryDirectory(prefix="phase3-mixed-")
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_cut_no_longer_rejects_mixed_source_plus_generative(self) -> None:
        """The pre-Phase-3 SystemExit raise is gone from cut.main."""
        cut_source = Path("artagents/executors/cut/run.py").read_text(encoding="utf-8")
        # Pre-Phase-3 raise looked like:
        #   if args.video is not None and arrangement_uses_generative_visuals(...):
        #       raise SystemExit("Source-cut mode cannot materialize generative visual_source ...")
        self.assertNotRegex(
            cut_source,
            r"raise\s+SystemExit\(\"Source-cut mode cannot materialize generative visual_source",
            "Phase 3 should have removed cut.py's mixed-mode rejection raise",
        )
        self.assertNotRegex(
            cut_source,
            r"if\s+args\.video\s+is\s+not\s+None\s+and\s+arrangement_uses_generative_visuals",
            "Phase 3 should have removed the args.video + arrangement_uses_generative_visuals branch",
        )

    def test_arrangement_uses_generative_visuals_classifier_still_works(self) -> None:
        """The classifier function is preserved (used as runtime helper, not orchestration gate)."""
        pool = pool_merge.merge_pool({
            "version": timeline_mod.POOL_VERSION,
            "generated_at": "2026-05-03T05:00:00Z",
            "entries": [],
        })
        arrangement = {
            "version": timeline_mod.ARRANGEMENT_VERSION,
            "generated_at": "2026-05-03T05:00:00Z",
            "brief_text": "Solo title card.",
            "target_duration_sec": 4.0,
            "clips": [
                {
                    "uuid": "0a1b2c3d",
                    "order": 1,
                    "audio_source": None,
                    "visual_source": {
                        "pool_id": "pool_g_text_card",
                        "role": "overlay",
                        "params": {"content": "Hi"},
                    },
                    "text_overlay": None,
                    "rationale": "Generated overlay.",
                }
            ],
        }
        timeline_mod.validate_arrangement(arrangement, {e["id"] for e in pool["entries"]})
        self.assertTrue(cut.arrangement_uses_generative_visuals(arrangement, pool))
        self.assertTrue(timeline_mod.is_all_generative_arrangement(arrangement, pool))

    def test_pure_generative_path_still_builds(self) -> None:
        """Regression guard — pure-generative cut still produces a timeline."""
        pool = pool_merge.merge_pool({
            "version": timeline_mod.POOL_VERSION,
            "generated_at": "2026-05-03T05:00:00Z",
            "entries": [],
        })
        arrangement = {
            "version": timeline_mod.ARRANGEMENT_VERSION,
            "generated_at": "2026-05-03T05:00:00Z",
            "brief_text": "Pure generative.",
            "target_duration_sec": 4.0,
            "clips": [
                {
                    "uuid": "0a1b2c3d",
                    "order": 1,
                    "audio_source": None,
                    "visual_source": {
                        "pool_id": "pool_g_text_card",
                        "role": "overlay",
                        "params": {"content": "Hello"},
                    },
                    "text_overlay": None,
                    "rationale": "Solo title card.",
                }
            ],
        }
        timeline_mod.validate_arrangement(arrangement, {e["id"] for e in pool["entries"]})
        args = argparse.Namespace(asset=[], video=None, audio=None)
        asset_paths, asset_urls = cut.resolve_asset_paths(args)
        registry, _sources = cut.build_registry(asset_paths, asset_urls, {"assets": {}}, None)
        config = cut.build_multitrack_timeline(
            arrangement, pool, registry, None, theme_slug="banodoco-default"
        )
        self.assertEqual(config["theme"], "banodoco-default")
        # Round-trip through Timeline.
        out_path = self._tempdir() / "hype.timeline.json"
        timeline_mod.save_timeline(config, out_path)
        loaded = Timeline.load(out_path)
        # Generated text card classifies as one of the synthetic arms (EFFECT/TEXT/IMAGE),
        # never as VIDEO/AUDIO/OPAQUE.
        kinds = sorted({view.classified_kind for view in loaded.classified_clips()})
        synthetic_arms = {
            ClipClassifiedKind.IMAGE,
            ClipClassifiedKind.TEXT,
            ClipClassifiedKind.EFFECT,
        }
        self.assertTrue(
            any(k in synthetic_arms for k in kinds),
            f"expected at least one synthetic arm in generative timeline, got {kinds}",
        )
        self.assertNotIn(ClipClassifiedKind.VIDEO, kinds)
        self.assertNotIn(ClipClassifiedKind.OPAQUE, kinds)
        # Reigh-compat: no persisted `kind` or `classified_kind` field on any clip.
        raw = json.loads(out_path.read_text(encoding="utf-8"))
        for clip in raw.get("clips", []):
            self.assertNotIn("kind", clip)
            self.assertNotIn("classified_kind", clip)


if __name__ == "__main__":
    unittest.main()
