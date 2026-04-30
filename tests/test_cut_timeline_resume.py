import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cut


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
REMOTION_NODE_MODULES = ROOT / "remotion" / "node_modules"


def remotion_launch_blocked(error: RuntimeError) -> bool:
    message = str(error)
    return (
        "Failed to launch the browser process" in message
        or "MachPortRendezvous" in message
        or "Permission denied (1100)" in message
    )


class CutTimelineResumeTest(unittest.TestCase):
    maxDiff = None

    def copy_examples(self) -> Path:
        tmp_root = Path(tempfile.mkdtemp(prefix="cut-resume-"))
        self.addCleanup(shutil.rmtree, tmp_root, ignore_errors=True)
        source_dir = tmp_root / "source"
        shutil.copytree(EXAMPLES, source_dir)
        return source_dir

    def test_same_dir_roundtrip_is_byte_identical(self) -> None:
        # Sprint 6 (SD-009): resume-mode backfills `output` if the loaded
        # timeline lacks it. This test pre-stamps `output` matching the theme
        # so the roundtrip remains byte-identical (the byte-equivalence claim
        # is for "no semantic drift", not "literally untouched"; if the input
        # already carries output, save_timeline preserves it verbatim).
        source_dir = self.copy_examples()
        timeline_path = source_dir / "hype.timeline.json"
        assets_path = source_dir / "hype.assets.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline.setdefault("output", {"resolution": "1920x1080", "fps": 30, "file": "output.mp4"})
        timeline_path.write_text(json.dumps(timeline, indent=2) + "\n", encoding="utf-8")
        original_timeline = timeline_path.read_bytes()
        original_assets = assets_path.read_bytes()

        result = cut.main(["--timeline", str(timeline_path), "--out", str(source_dir)])

        self.assertEqual(result, 0)
        self.assertEqual(timeline_path.read_bytes(), original_timeline)
        self.assertEqual(assets_path.read_bytes(), original_assets)
        self.assertFalse((source_dir / "hype.edl.csv").exists())

    def test_different_out_rebases_registry_paths(self) -> None:
        source_dir = self.copy_examples()
        timeline_path = source_dir / "hype.timeline.json"
        out_dir = source_dir.parent / "out"
        original_timeline = json.loads(timeline_path.read_text(encoding="utf-8"))

        result = cut.main(["--timeline", str(timeline_path), "--out", str(out_dir)])

        self.assertEqual(result, 0)
        # Sprint 6 (SD-009): resume-mode now backfills `output` from the theme
        # when missing. Other fields (theme slug, clips, tracks) round-trip
        # verbatim.
        rewritten = json.loads((out_dir / "hype.timeline.json").read_text(encoding="utf-8"))
        for key in ("theme", "clips", "tracks", "theme_overrides"):
            if key in original_timeline:
                self.assertEqual(rewritten.get(key), original_timeline[key])
        self.assertIn("output", rewritten)
        self.assertEqual(set(rewritten["output"].keys()) & {"resolution", "fps", "file"},
                         {"resolution", "fps", "file"})
        registry = json.loads((out_dir / "hype.assets.json").read_text(encoding="utf-8"))
        self.assertEqual(
            Path(registry["assets"]["main"]["file"]),
            (source_dir / "main.mp4").resolve(),
        )
        self.assertEqual(
            Path(registry["assets"]["broll"]["file"]),
            (source_dir / "broll.mp4").resolve(),
        )
        self.assertTrue(Path(registry["assets"]["main"]["file"]).is_absolute())
        self.assertFalse((out_dir / "hype.edl.csv").exists())

    def test_conflicting_flags_are_rejected(self) -> None:
        source_dir = self.copy_examples()
        timeline_path = source_dir / "hype.timeline.json"
        out_dir = source_dir.parent / "out"
        conflicts = [
            ("--scenes", str(source_dir / "scenes.json")),
            ("--video", str(source_dir / "main.mp4")),
            ("--shots", str(source_dir / "shots.json")),
            ("--transcript", str(source_dir / "transcript.json")),
            ("--primary-asset", "main"),
            ("--asset", "main=/tmp/main.mp4"),
        ]
        self.assertEqual(len(conflicts), 6)

        for flag, value in conflicts:
            with self.subTest(flag=flag):
                with self.assertRaises(SystemExit) as ctx:
                    cut.main(["--timeline", str(timeline_path), "--out", str(out_dir), flag, value])
                self.assertIn(flag, str(ctx.exception))

    def test_missing_asset_key_is_rejected(self) -> None:
        source_dir = self.copy_examples()
        timeline_path = source_dir / "hype.timeline.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline["clips"][0]["asset"] = "ghost"
        timeline_path.write_text(json.dumps(timeline, indent=2) + "\n", encoding="utf-8")

        with self.assertRaises(SystemExit) as ctx:
            cut.main(["--timeline", str(timeline_path), "--out", str(source_dir.parent / "out")])

        self.assertIn("ghost", str(ctx.exception))

    def test_ffmpeg_legacy_renderer_is_rejected(self) -> None:
        source_dir = self.copy_examples()
        timeline_path = source_dir / "hype.timeline.json"

        with self.assertRaises(SystemExit) as ctx:
            cut.main(
                [
                    "--timeline",
                    str(timeline_path),
                    "--out",
                    str(source_dir.parent / "out"),
                    "--render",
                    "--renderer",
                    "ffmpeg-legacy",
                ]
            )

        self.assertEqual(ctx.exception.code, 2)

    def test_metadata_carry_forward_preserves_clip_rationale(self) -> None:
        source_dir = self.copy_examples()
        timeline_path = source_dir / "hype.timeline.json"
        metadata_path = source_dir / "hype.metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["generated_at"] = "2025-01-01T00:00:00Z"
        metadata["clips"]["clip_001"]["pick_rationale"] = "Keep this rationale."
        metadata["clips"]["clip_999"] = {"pick_rationale": "orphan"}
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

        out_dir = source_dir.parent / "out"
        result = cut.main(["--timeline", str(timeline_path), "--out", str(out_dir)])

        self.assertEqual(result, 0)
        updated = json.loads((out_dir / "hype.metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(updated["clips"]["clip_001"]["pick_rationale"], "Keep this rationale.")
        self.assertNotIn("clip_999", updated["clips"])
        self.assertEqual(updated["sources"], metadata["sources"])
        self.assertNotEqual(updated["generated_at"], metadata["generated_at"])
        self.assertEqual(updated["pipeline"]["config_snapshot"]["mode"], "timeline_resume")

    def test_resume_mode_render_smoke(self) -> None:
        if shutil.which("ffmpeg") is None or shutil.which("npx") is None or not REMOTION_NODE_MODULES.exists():
            self.skipTest("ffmpeg, npx, and remotion/node_modules are required for the render smoke")

        source_dir = self.copy_examples()
        timeline_path = source_dir / "hype.timeline.json"
        out_dir = source_dir.parent / "rendered"

        try:
            result = cut.main(["--timeline", str(timeline_path), "--out", str(out_dir), "--render"])
        except RuntimeError as exc:
            if remotion_launch_blocked(exc):
                self.skipTest(f"Remotion browser launch is blocked in this environment: {exc}")
            raise

        self.assertEqual(result, 0)
        output = out_dir / "hype.mp4"
        self.assertTrue(output.exists())
        self.assertGreater(output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
