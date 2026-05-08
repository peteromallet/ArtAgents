import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from astrid.packs.builtin.editor_review import run as editor_review
from astrid import timeline


class EditorReviewTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="editor-review-test-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def arrangement(self) -> dict:
        return {
            "version": timeline.ARRANGEMENT_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "brief_text": "Make it sharp.",
            "target_duration_sec": 80.0,
            "clips": [
                {
                    "order": 1,
                    "uuid": "00000001",
                    "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 8.0]},
                    "visual_source": None,
                    "text_overlay": None,
                    "rationale": "Hook.",
                },
                {
                    "order": 2,
                    "uuid": "00000002",
                    "audio_source": {"pool_id": "pool_d_0002", "trim_sub_range": [10.0, 18.0]},
                    "visual_source": None,
                    "text_overlay": None,
                    "rationale": "Build.",
                },
            ],
        }

    def valid_note(self, **overrides) -> dict:
        note = {
            "clip_order": 1,
            "clip_uuid": "00000001",
            "observation": "Trim the pause.",
            "brief_impact": "Improves pace.",
            "action": "micro-fix",
            "action_detail": {"trim_delta_start_sec": 0.1, "trim_delta_end_sec": -0.2, "reason": "Tighter."},
            "priority": "medium",
            "candidate_pool_id": None,
        }
        note.update(overrides)
        return note

    def test_sample_frames_returns_expected_count(self) -> None:
        tmp_dir = self.make_tempdir()
        hype_mp4 = tmp_dir / "hype.mp4"
        cache_dir = tmp_dir / "frames"
        hype_mp4.write_bytes(b"video")
        cache_dir.mkdir()
        for index in range(1, 51):
            (cache_dir / f"frame_{index:03d}.jpg").write_bytes(b"jpg")
        calls = []

        def ffprobe_runner(cmd, **kwargs):
            calls.append(("ffprobe", cmd, kwargs))
            return SimpleNamespace(stdout="80.0\n")

        def ffmpeg_runner(cmd, **kwargs):
            calls.append(("ffmpeg", cmd, kwargs))
            return SimpleNamespace(stdout="", stderr="")

        frames = editor_review.sample_frames(
            hype_mp4,
            cache_dir,
            ffmpeg_runner=ffmpeg_runner,
            ffprobe_runner=ffprobe_runner,
        )

        self.assertEqual(len(frames), 50)
        ffmpeg_cmd = calls[-1][1]
        self.assertEqual(ffmpeg_cmd[ffmpeg_cmd.index("-i") + 1], str(hype_mp4))
        self.assertNotIn("-c", ffmpeg_cmd)
        self.assertNotIn("copy", ffmpeg_cmd)
        self.assertNotIn(str(hype_mp4), ffmpeg_cmd[ffmpeg_cmd.index("-i") + 2 :])

    def test_note_schema_validation(self) -> None:
        arrangement = self.arrangement()
        with self.assertRaises(ValueError):
            editor_review._validate_editor_notes({"notes": [self.valid_note(clip_order=99)]}, arrangement)
        with self.assertRaises(ValueError):
            editor_review._validate_editor_notes(
                {
                    "notes": [
                        self.valid_note(
                            action="swap",
                            action_detail={"candidate_pool_id": "pool_v_0002", "role": "overlay", "reason": "Better fit."},
                            candidate_pool_id=None,
                        )
                    ]
                },
                arrangement,
            )
        with self.assertRaises(ValueError):
            editor_review._validate_editor_notes(
                {"notes": [self.valid_note(action="reorder", action_detail={})]},
                arrangement,
            )

        valid = {
            "notes": [
                self.valid_note(),
                {
                    "clip_order": 1,
                    "clip_uuid": "00000001",
                    "observation": "Needs a breath.",
                    "brief_impact": "Improves pacing.",
                    "action": "insert-stinger",
                    "action_detail": {
                        "after_clip_order": 1,
                        "candidate_pool_id": "pool_v_0002",
                        "duration_sec": 3.0,
                        "reason": "Adds a beat.",
                    },
                    "priority": "low",
                    "candidate_pool_id": None,
                },
            ]
        }
        editor_review._validate_editor_notes(valid, arrangement)

    def test_notes_overlap_ratio_uuid_stable_across_reorder(self) -> None:
        prev = [
            {"clip_order": 1, "clip_uuid": "00000001", "action": "swap"},
            {"clip_order": 2, "clip_uuid": "00000002", "action": "micro-fix"},
        ]
        curr = [
            {"clip_order": 2, "clip_uuid": "00000001", "action": "swap"},
            {"clip_order": 1, "clip_uuid": "00000002", "action": "micro-fix"},
        ]
        self.assertEqual(editor_review.notes_overlap_ratio(prev, curr), 1.0)

    def test_convergence_overlap_low_returns_false(self) -> None:
        prev = [
            {"clip_order": 1, "clip_uuid": "00000001", "action": "swap"},
            {"clip_order": 2, "clip_uuid": "00000002", "action": "micro-fix"},
        ]
        curr = [
            {"clip_order": 3, "clip_uuid": "00000003", "action": "swap"},
            {"clip_order": 4, "clip_uuid": "00000004", "action": "micro-fix"},
        ]
        self.assertLess(editor_review.notes_overlap_ratio(prev, curr), 0.8)
        self.assertEqual(editor_review.notes_overlap_ratio([], []), 0.0)

    def test_review_rejects_uuid_order_mismatch(self) -> None:
        arrangement = self.arrangement()
        with self.assertRaises(ValueError):
            editor_review._validate_editor_notes(
                {"notes": [self.valid_note(clip_order=1, clip_uuid="00000002")]},
                arrangement,
            )

    def test_verdict_to_action_routing(self) -> None:
        self.assertEqual(editor_review.plan_next_action({"verdict": "ship", "notes": []}), "ship")
        self.assertEqual(
            editor_review.plan_next_action(
                {"verdict": "iterate", "notes": [{"action": "accept"}, {"action": "micro-fix"}]}
            ),
            "micro-fix",
        )
        self.assertEqual(editor_review.plan_next_action({"verdict": "iterate", "notes": [{"action": "swap"}]}), "rework")

    def test_cli_uses_fake_clients(self) -> None:
        tmp_dir = self.make_tempdir()
        brief_dir = tmp_dir / "out" / "briefs" / "brief"
        run_dir = tmp_dir / "out"
        brief_dir.mkdir(parents=True)
        (brief_dir / "hype.mp4").write_bytes(b"video")
        (brief_dir / "brief.txt").write_text("Make it sharp.", encoding="utf-8")
        timeline.save_arrangement(self.arrangement(), brief_dir / "arrangement.json", {"pool_d_0001", "pool_d_0002"})
        (brief_dir / "refine.json").write_text(json.dumps({"flags": []}), encoding="utf-8")
        timeline.save_metadata(
            {"version": 1, "generated_at": "2026-04-21T12:00:00Z", "pipeline": {}, "clips": {}, "sources": {}},
            brief_dir / "hype.metadata.json",
        )
        timeline.save_pool(
            {
                "version": timeline.POOL_VERSION,
                "generated_at": "2026-04-21T12:00:00Z",
                "source_slug": "src",
                "entries": [
                    {
                        "id": "pool_d_0001",
                        "kind": "source",
                    "category": "dialogue",
                        "asset": "main",
                        "src_start": 0.0,
                        "src_end": 10.0,
                        "duration": 10.0,
                        "source_ids": {},
                        "scores": {},
                        "excluded": False,
                        "text": "Quote",
                    },
                    {
                        "id": "pool_d_0002",
                        "kind": "source",
                    "category": "dialogue",
                        "asset": "main",
                        "src_start": 10.0,
                        "src_end": 20.0,
                        "duration": 10.0,
                        "source_ids": {},
                        "scores": {},
                        "excluded": False,
                        "text": "Quote 2",
                    },
                ],
            },
            run_dir / "pool.json",
        )
        (run_dir / "quality_zones.json").write_text(json.dumps({"zones": []}), encoding="utf-8")
        frame = tmp_dir / "frame_001.jpg"
        frame.write_bytes(b"jpg")

        class FakeClaude:
            def __init__(self):
                self.calls = []

            def complete_json(self, **kwargs):
                self.calls.append(kwargs)
                return {"iteration": 1, "notes": [], "verdict": "ship", "ship_confidence": 0.95}

        fake_claude = FakeClaude()
        inspect_calls = []

        def fake_run(cmd, **kwargs):
            inspect_calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="SCRIPT\nSTRUCTURE\n", stderr="")

        with mock.patch.object(editor_review, "sample_frames", return_value=[frame]), mock.patch.object(
            editor_review, "transcribe_hype_audio", return_value={"text": "hello", "segments": []}
        ), mock.patch.object(editor_review, "build_openai_client", return_value=object()), mock.patch.object(
            editor_review, "build_claude_client", return_value=fake_claude
        ), mock.patch.object(editor_review.subprocess, "run", side_effect=fake_run):
            result = editor_review.main(
                [
                    "--brief-dir",
                    str(brief_dir),
                    "--run-dir",
                    str(run_dir),
                    "--out",
                    str(brief_dir),
                    "--iteration",
                    "2",
                ]
            )

        self.assertEqual(result, 0)
        review = json.loads((brief_dir / "editor_review.json").read_text(encoding="utf-8"))
        self.assertEqual(review["iteration"], 2)
        self.assertEqual(review["verdict"], "ship")
        self.assertEqual(len(fake_claude.calls), 1)
        self.assertEqual(inspect_calls[0][3], str(brief_dir.resolve()))
        self.assertNotEqual(inspect_calls[0][3], str(run_dir.resolve()))


if __name__ == "__main__":
    unittest.main()
