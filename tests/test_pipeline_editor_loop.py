import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from artagents.executors.editor_review import run as editor_review
from artagents import pipeline
from artagents import timeline


class PipelineEditorLoopTest(unittest.TestCase):
    maxDiff = None

    def make_workspace(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="pipeline-editor-loop-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def seed_inputs(self, root: Path) -> tuple[Path, Path, Path]:
        video = root / "main.mp4"
        audio = root / "audio.wav"
        brief = root / "brief.txt"
        video.write_bytes(b"video")
        audio.write_bytes(b"audio")
        brief.write_text("Make it sharp.", encoding="utf-8")
        return video, audio, brief

    def arrangement(self, start: float = 0.0, end: float = 8.0) -> dict:
        return {
            "version": timeline.ARRANGEMENT_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "brief_text": "Make it sharp.",
            "target_duration_sec": 80.0,
            "clips": [
                {
                    "order": 1,
                    "uuid": "00000001",
                    "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [start, end]},
                    "visual_source": None,
                    "text_overlay": None,
                    "rationale": "Hook.",
                }
            ],
        }

    def pool(self) -> dict:
        return {
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
                    "id": "pool_v_0002",
                    "kind": "source",
                    "category": "visual",
                    "asset": "main",
                    "src_start": 10.0,
                    "src_end": 18.0,
                    "duration": 8.0,
                    "source_ids": {},
                    "scores": {},
                    "excluded": False,
                },
            ],
        }

    def review(self, verdict: str, notes: list[dict] | None = None, confidence: float = 0.5) -> dict:
        return {"iteration": 1, "notes": notes or [], "verdict": verdict, "ship_confidence": confidence}

    def micro_fix_note(self) -> dict:
        return {
            "clip_order": 1,
            "clip_uuid": "00000001",
            "observation": "Pause is too long.",
            "brief_impact": "Tightens pace.",
            "action": "micro-fix",
            "action_detail": {"trim_delta_start_sec": 0.25, "trim_delta_end_sec": -0.5, "reason": "Tighter."},
            "priority": "high",
            "candidate_pool_id": None,
        }

    def swap_note(self) -> dict:
        return {
            "clip_order": 1,
            "clip_uuid": "00000001",
            "observation": "Shot does not match.",
            "brief_impact": "Weakens the hook.",
            "action": "swap",
            "action_detail": {"candidate_pool_id": "pool_v_0002", "role": "overlay", "reason": "Better fit."},
            "priority": "high",
            "candidate_pool_id": "pool_v_0002",
        }

    def invoke(
        self,
        root: Path,
        extra_args: list[str],
        *,
        reviews: list[dict] | None = None,
    ) -> tuple[int, list[tuple[str, list[str]]], Path]:
        video, audio, brief = self.seed_inputs(root)
        out_dir = root / "out"
        broll = root / "broll.mp4"
        broll.write_bytes(b"broll")
        calls: list[tuple[str, list[str]]] = []
        review_queue = list(reviews or [])

        def write_sentinels(step: pipeline.Step, args) -> None:
            for sentinel_path in pipeline.sentinel_paths(step, args):
                sentinel_path.parent.mkdir(parents=True, exist_ok=True)
                if step.name in {"arrange", "arrange_revise"} and sentinel_path.name == "arrangement.json":
                    timeline.save_arrangement(self.arrangement(), sentinel_path, {"pool_d_0001", "pool_v_0002"})
                elif step.name == "pool_build" and sentinel_path.name == "pool.json":
                    timeline.save_pool(self.pool(), sentinel_path)
                elif step.name == "editor_review":
                    review = review_queue.pop(0) if review_queue else self.review("ship", confidence=0.95)
                    review["iteration"] = int(getattr(args, "editor_iteration", 1))
                    sentinel_path.write_text(json.dumps(review), encoding="utf-8")
                else:
                    sentinel_path.write_text(f"{step.name}:{sentinel_path.name}\n", encoding="utf-8")

        def fake_run_step(step: pipeline.Step, cmd: list[str], args) -> int:
            calls.append((step.name, list(cmd)))
            logs_dir = pipeline.log_dir_for_step(step, args)
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / f"{step.name}.log").write_text(f"ran {step.name}\n", encoding="utf-8")
            write_sentinels(step, args)
            return 0

        argv = [
            "--video",
            str(video),
            "--audio",
            str(audio),
            "--brief",
            str(brief),
            "--out",
            str(out_dir),
            "--asset",
            f"broll={broll}",
            "--primary-asset",
            "broll",
            *extra_args,
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(pipeline, "run_step", side_effect=fake_run_step):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = pipeline.main(argv)
        return result, calls, out_dir

    def test_editor_review_skipped_when_no_render(self) -> None:
        root = self.make_workspace()
        result, calls, _ = self.invoke(root, [])

        self.assertEqual(result, 0)
        self.assertNotIn("editor_review", [name for name, _ in calls])

    def test_editor_review_ship_ends_pipeline(self) -> None:
        root = self.make_workspace()
        result, calls, _ = self.invoke(root, ["--render"], reviews=[self.review("ship", confidence=0.96)])
        names = [name for name, _ in calls]

        self.assertEqual(result, 0)
        self.assertEqual(names.count("editor_review"), 1)
        self.assertEqual(names.count("cut"), 1)
        self.assertEqual(names.count("refine"), 1)
        self.assertEqual(names.count("render"), 1)

    def test_editor_review_micro_fix_reruns_once(self) -> None:
        root = self.make_workspace()
        result, calls, out_dir = self.invoke(
            root,
            ["--render"],
            reviews=[self.review("iterate", [self.micro_fix_note()]), self.review("ship", confidence=0.95)],
        )
        names = [name for name, _ in calls]
        arrangement = timeline.load_arrangement(out_dir / "briefs" / "out" / "arrangement.json")

        self.assertEqual(result, 0)
        self.assertEqual(names.count("cut"), 2)
        self.assertEqual(names.count("refine"), 2)
        self.assertEqual(names.count("render"), 2)
        self.assertEqual(names.count("editor_review"), 2)
        self.assertNotIn("arrange_revise", names)
        self.assertEqual(arrangement["clips"][0]["audio_source"]["trim_sub_range"], [0.25, 7.5])

    def test_editor_review_rework_invokes_revise(self) -> None:
        root = self.make_workspace()
        result, calls, _ = self.invoke(
            root,
            ["--render"],
            reviews=[self.review("iterate", [self.swap_note()]), self.review("ship", confidence=0.93)],
        )
        names = [name for name, _ in calls]
        revise_commands = [cmd for name, cmd in calls if name == "arrange_revise"]

        self.assertEqual(result, 0)
        self.assertEqual(names.count("arrange_revise"), 1)
        self.assertEqual(names.count("editor_review"), 2)
        self.assertIn("--revise", revise_commands[0])
        self.assertIn("--from-arrangement", revise_commands[0])
        self.assertIn("--editor-notes", revise_commands[0])

    def test_editor_review_budget_cap_is_two(self) -> None:
        root = self.make_workspace()
        result, calls, _ = self.invoke(
            root,
            ["--render"],
            reviews=[
                self.review("iterate", [self.micro_fix_note()]),
                self.review("iterate", [self.micro_fix_note()]),
                self.review("iterate", [self.micro_fix_note()]),
            ],
        )

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls].count("editor_review"), 2)

    def test_max_editor_passes_rejects_three(self) -> None:
        root = self.make_workspace()
        video, _audio, brief = self.seed_inputs(root)
        with mock.patch.object(pipeline, "run_step"):
            with self.assertRaises(SystemExit):
                pipeline.resolve_args(
                    [
                        "--video",
                        str(video),
                        "--brief",
                        str(brief),
                        "--out",
                        str(root / "out"),
                        "--max-editor-passes",
                        "3",
                    ]
                )

    def test_editor_review_inspect_cut_subprocess_uses_brief_dir(self) -> None:
        root = self.make_workspace()
        brief_dir = root / "out" / "briefs" / "brief"
        run_dir = root / "out"
        brief_dir.mkdir(parents=True)
        (brief_dir / "hype.mp4").write_bytes(b"video")
        (brief_dir / "brief.txt").write_text("Make it sharp.", encoding="utf-8")
        timeline.save_arrangement(self.arrangement(), brief_dir / "arrangement.json", {"pool_d_0001", "pool_v_0002"})
        (brief_dir / "refine.json").write_text(json.dumps({"flags": []}), encoding="utf-8")
        timeline.save_metadata(
            {"version": 1, "generated_at": "2026-04-21T12:00:00Z", "pipeline": {}, "clips": {}, "sources": {}},
            brief_dir / "hype.metadata.json",
        )
        timeline.save_pool(self.pool(), run_dir / "pool.json")
        (run_dir / "quality_zones.json").write_text(json.dumps({"zones": []}), encoding="utf-8")
        frame = root / "frame_001.jpg"
        frame.write_bytes(b"jpg")
        inspect_calls = []

        class FakeClaude:
            def complete_json(self, **_kwargs):
                return self_outer.review("ship", confidence=0.95)

        self_outer = self

        def fake_run(cmd, **_kwargs):
            inspect_calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="SCRIPT\nSTRUCTURE\n", stderr="")

        with mock.patch.object(pipeline, "run_step"), mock.patch.object(
            editor_review, "sample_frames", return_value=[frame]
        ), mock.patch.object(
            editor_review, "transcribe_hype_audio", return_value={"text": "hello", "segments": []}
        ), mock.patch.object(
            editor_review, "build_openai_client", return_value=object()
        ), mock.patch.object(
            editor_review, "build_claude_client", return_value=FakeClaude()
        ), mock.patch.object(
            editor_review.subprocess, "run", side_effect=fake_run
        ):
            result = editor_review.main(
                ["--brief-dir", str(brief_dir), "--run-dir", str(run_dir), "--out", str(brief_dir)]
            )

        self.assertEqual(result, 0)
        self.assertEqual(inspect_calls[0][3], str(brief_dir.resolve()))
        self.assertNotEqual(inspect_calls[0][3], str(run_dir.resolve()))

    def test_no_hype_mp4_copy_in_frame_sampling(self) -> None:
        root = self.make_workspace()
        hype_mp4 = root / "hype.mp4"
        cache_dir = root / "frames"
        hype_mp4.write_bytes(b"video")
        cache_dir.mkdir()
        (cache_dir / "frame_001.jpg").write_bytes(b"jpg")
        commands = []

        def ffprobe_runner(cmd, **_kwargs):
            return SimpleNamespace(stdout="1.0\n")

        def ffmpeg_runner(cmd, **_kwargs):
            commands.append(cmd)
            return SimpleNamespace(stdout="", stderr="")

        with mock.patch.object(pipeline, "run_step"):
            editor_review.sample_frames(
                hype_mp4,
                cache_dir,
                ffprobe_runner=ffprobe_runner,
                ffmpeg_runner=ffmpeg_runner,
            )

        ffmpeg_cmd = commands[0]
        self.assertEqual(ffmpeg_cmd[ffmpeg_cmd.index("-i") + 1], str(hype_mp4))
        self.assertNotIn("-c", ffmpeg_cmd)
        self.assertNotIn("copy", ffmpeg_cmd)
        self.assertNotIn(str(hype_mp4), ffmpeg_cmd[ffmpeg_cmd.index("-i") + 2 :])


if __name__ == "__main__":
    unittest.main()
