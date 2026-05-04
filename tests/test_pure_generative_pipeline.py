import argparse
import json
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from artagents.packs.builtin.arrange import run as arrange
from artagents.packs.builtin.cut import run as cut
from artagents import pipeline
from artagents.packs.builtin.pool_merge import run as pool_merge
from artagents import timeline


class PureGenerativePipelineTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        tmp = tempfile.TemporaryDirectory(prefix="pure-generative-")
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def make_wav(self, path: Path, seconds: int = 10) -> None:
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * 16000 * seconds)

    def test_no_video_step_list_and_cut_command(self) -> None:
        tmp = self.make_tempdir()
        audio = tmp / "rant.wav"
        brief = tmp / "brief.txt"
        self.make_wav(audio)
        brief.write_text("Make a quote card.\n", encoding="utf-8")
        args = pipeline.resolve_args(["--audio", str(audio), "--brief", str(brief), "--out", str(tmp / "out")])

        step_names = [step.name for step in pipeline.select_steps(args)]
        for skipped in ("scenes", "quality_zones", "shots", "triage", "scene_describe", "quote_scout", "pool_build"):
            self.assertNotIn(skipped, step_names)
        self.assertIn("pool_merge", step_names)

        args.out.mkdir(parents=True)
        (args.out / "transcript.json").write_text('{"segments":[]}\n', encoding="utf-8")
        cmd = pipeline.build_pool_cut_cmd(args)
        self.assertIn("--audio", cmd)
        self.assertIn(str(args.audio), cmd)
        self.assertNotIn("--video", cmd)
        self.assertNotIn("--scenes", cmd)
        arrange_step = next(step for step in pipeline.select_steps(args) if step.name == "arrange")
        arrange_cmd = arrange_step.build_cmd(args)
        self.assertIn("--target-duration", arrange_cmd)
        self.assertIn("--allow-generative-effects", arrange_cmd)
        self.assertNotIn("--no-audio", arrange_cmd)
        for audio_step in ("transcribe", "refine", "editor_review", "validate"):
            self.assertIn(audio_step, step_names)

    def test_no_audio_resolve_args_requires_target_duration(self) -> None:
        tmp = self.make_tempdir()
        brief = tmp / "brief.txt"
        brief.write_text("Make a visual-only explainer.\n", encoding="utf-8")

        with self.assertRaises(SystemExit) as exc_info:
            pipeline.resolve_args(["--brief", str(brief), "--out", str(tmp / "out")])

        self.assertEqual(exc_info.exception.code, 2)

    def test_no_audio_step_list_and_arrange_command(self) -> None:
        tmp = self.make_tempdir()
        brief = tmp / "brief.txt"
        brief.write_text("Make a visual-only explainer.\n", encoding="utf-8")
        args = pipeline.resolve_args(["--brief", str(brief), "--out", str(tmp / "out"), "--target-duration", "28"])

        self.assertIsNone(args.audio)
        step_names = [step.name for step in pipeline.select_steps(args)]
        for skipped in (
            "scenes",
            "quality_zones",
            "shots",
            "triage",
            "scene_describe",
            "quote_scout",
            "pool_build",
            "transcribe",
            "refine",
            "editor_review",
            "validate",
        ):
            self.assertNotIn(skipped, step_names)
        self.assertIn("pool_merge", step_names)
        self.assertIn("arrange", step_names)
        self.assertIn("cut", step_names)

        arrange_step = next(step for step in pipeline.select_steps(args) if step.name == "arrange")
        arrange_cmd = arrange_step.build_cmd(args)
        self.assertIn("--target-duration", arrange_cmd)
        self.assertEqual(arrange_cmd[arrange_cmd.index("--target-duration") + 1], "28.000000")
        self.assertIn("--allow-generative-effects", arrange_cmd)
        self.assertIn("--no-audio", arrange_cmd)
        self.assertNotIn("--audio", pipeline.build_pool_cut_cmd(args))

    def test_source_cut_step_list_keeps_generative_effects_out_of_arrange(self) -> None:
        tmp = self.make_tempdir()
        video = tmp / "source.mp4"
        brief = tmp / "brief.txt"
        video.write_bytes(b"fake mp4")
        brief.write_text("Cut source footage only.\n", encoding="utf-8")
        args = pipeline.resolve_args(["--video", str(video), "--brief", str(brief), "--out", str(tmp / "out")])
        arrange_step = next(step for step in pipeline.select_steps(args) if step.name == "arrange")
        arrange_cmd = arrange_step.build_cmd(args)
        self.assertNotIn("--target-duration", arrange_cmd)
        self.assertNotIn("--allow-generative-effects", arrange_cmd)

    def test_pool_merge_is_idempotent(self) -> None:
        tmp = self.make_tempdir()
        pool = {"version": timeline.POOL_VERSION, "generated_at": "2026-04-21T12:00:00Z", "entries": []}
        first = pool_merge.merge_pool(pool)
        second = pool_merge.merge_pool(first)
        entries = [entry for entry in second["entries"] if entry["id"] == "pool_g_text_card"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(first, second)

    def test_audio_probe_and_generative_materialization(self) -> None:
        tmp = self.make_tempdir()
        audio = tmp / "rant.wav"
        self.make_wav(audio)
        args = argparse.Namespace(asset=[], video=None, audio=str(audio))
        asset_paths, asset_urls = cut.resolve_asset_paths(args)
        self.assertIn("rant", asset_paths)
        registry, _sources = cut.build_registry(asset_paths, asset_urls, {"assets": {}}, None)
        self.assertEqual(registry["assets"]["rant"]["type"], "audio")

        pool = pool_merge.merge_pool({"version": timeline.POOL_VERSION, "generated_at": "2026-04-21T12:00:00Z", "entries": []})
        arrangement = {
            "version": timeline.ARRANGEMENT_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "brief_text": "Make a quote card.",
            "target_duration_sec": 10.0,
            "clips": [
                {
                    "uuid": "a3f4b21c",
                    "order": 1,
                    "audio_source": None,
                    "visual_source": {
                        "pool_id": "pool_g_text_card",
                        "role": "overlay",
                        "params": {"content": "Hello"},
                    },
                    "text_overlay": None,
                    "rationale": "Use a generated quote card.",
                }
            ],
        }
        timeline.validate_arrangement(arrangement, {entry["id"] for entry in pool["entries"]})
        self.assertTrue(timeline.is_all_generative_arrangement(arrangement, pool))
        self.assertTrue(cut.arrangement_uses_generative_visuals(arrangement, pool))
        config = cut.build_multitrack_timeline(arrangement, pool, registry, None, theme_slug="banodoco-default")
        self.assertEqual(config["theme"], "banodoco-default")
        self.assertEqual([track["id"] for track in config["tracks"]], ["v1", "v2", "a1"])
        self.assertTrue(any(clip["track"] == "a1" and clip["asset"] == "rant" for clip in config["clips"]))
        text_card = next(clip for clip in config["clips"] if clip["clipType"] == "text-card")
        self.assertEqual(text_card["params"]["content"], "Hello")

    def test_no_audio_cut_omits_audio_track_and_rant_clip(self) -> None:
        tmp = self.make_tempdir()
        pool = pool_merge.merge_pool({"version": timeline.POOL_VERSION, "generated_at": "2026-04-21T12:00:00Z", "entries": []})
        arrangement = {
            "version": timeline.ARRANGEMENT_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "brief_text": "Make a quote card.",
            "target_duration_sec": 4.0,
            "clips": [
                {
                    "uuid": "a3f4b21c",
                    "order": 1,
                    "audio_source": None,
                    "visual_source": {
                        "pool_id": "pool_g_text_card",
                        "role": "primary",
                        "params": {"content": "Hello"},
                    },
                    "text_overlay": None,
                    "rationale": "Use a generated quote card.",
                }
            ],
        }
        pool_path = tmp / "pool.json"
        arrangement_path = tmp / "arrangement.json"
        brief_path = tmp / "brief.txt"
        timeline.save_pool(pool, pool_path)
        timeline.save_arrangement(arrangement, arrangement_path, {entry["id"] for entry in pool["entries"]})
        brief_path.write_text("Make a quote card.\n", encoding="utf-8")

        result = cut.main(
            [
                "--pool",
                str(pool_path),
                "--arrangement",
                str(arrangement_path),
                "--brief",
                str(brief_path),
                "--out",
                str(tmp / "out"),
            ]
        )

        self.assertEqual(result, 0)
        config = timeline.load_timeline(tmp / "out" / "hype.timeline.json")
        self.assertNotIn("a1", [track["id"] for track in config["tracks"]])
        self.assertFalse(any(clip.get("track") == "a1" for clip in config["clips"]))
        self.assertFalse(any(clip.get("id") == "clip_a_rant" for clip in config["clips"]))

    def test_target_duration_tolerance_and_source_window(self) -> None:
        pool = pool_merge.merge_pool({"version": timeline.POOL_VERSION, "generated_at": "2026-04-21T12:00:00Z", "entries": []})
        response = {
            "target_duration_sec": 10.4,
            "clips": [
                {
                    "order": 1,
                    "audio_source": None,
                    "visual_source": {"pool_id": "pool_g_text_card", "role": "overlay", "params": {"content": "Hi"}},
                    "text_overlay": None,
                    "rationale": "Quote card.",
                }
            ],
        }
        arrangement = arrange._validated_arrangement(response, pool, "Brief", 10.0)
        arrange._assign_clip_uuids(arrangement["clips"])
        timeline.validate_arrangement(arrangement, arrange._eligible_pool_ids(pool))

        source_arrangement = dict(arrangement)
        source_arrangement["target_duration_sec"] = 10.0
        with self.assertRaises(timeline.ArrangementDurationError):
            timeline.validate_arrangement_duration_window(source_arrangement)


if __name__ == "__main__":
    unittest.main()
