import os
import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents import pipeline


ROOT = Path(__file__).resolve().parents[1]
POOL_RENDER_STEPS = [
    "transcribe",
    "scenes",
    "quality_zones",
    "shots",
    "triage",
    "scene_describe",
    "quote_scout",
    "pool_build",
    "pool_merge",
    "arrange",
    "cut",
    "refine",
    "render",
    "editor_review",
    "validate",
]
POOL_NO_RENDER_STEPS = [
    "transcribe",
    "scenes",
    "quality_zones",
    "shots",
    "triage",
    "scene_describe",
    "quote_scout",
    "pool_build",
    "pool_merge",
    "arrange",
    "cut",
]


class PipelineCachingTest(unittest.TestCase):
    maxDiff = None

    def make_workspace(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="pipeline-tests-", dir=ROOT))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def seed_inputs(self, root: Path) -> tuple[Path, Path, Path]:
        video = root / "main.mp4"
        audio = root / "audio.wav"
        plan = root / "plan.json"
        video.write_bytes(b"video")
        audio.write_bytes(b"audio")
        plan.write_text("[]", encoding="utf-8")
        return video, audio, plan

    def invoke(
        self,
        root: Path,
        extra_args: list[str],
        *,
        returncode_by_step: dict[str, int] | None = None,
        brief_flag: str = "--brief",
    ) -> tuple[int, list[tuple[str, list[str]]], str, str, Path]:
        video, audio, plan = self.seed_inputs(root)
        out_dir = root / "out"
        broll = root / "broll.mp4"
        broll.write_bytes(b"broll")
        calls: list[tuple[str, list[str]]] = []
        returncode_by_step = returncode_by_step or {}

        def fake_run_step(step: pipeline.Step, cmd: list[str], args) -> int:
            calls.append((step.name, list(cmd)))
            logs_dir = pipeline.log_dir_for_step(step, args)
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = logs_dir / f"{step.name}.log"
            exit_code = returncode_by_step.get(step.name, 0)
            lines = [f"{step.name}-line-{index}\n" for index in range(50)] if exit_code else [f"ran {step.name}\n"]
            log_path.write_text("".join(lines), encoding="utf-8")
            if exit_code:
                pipeline.print_log_tail(step.name, log_path)
                return exit_code
            for sentinel_path in pipeline.sentinel_paths(step, args):
                sentinel_path.parent.mkdir(parents=True, exist_ok=True)
                sentinel_path.write_text(f"{step.name}:{sentinel_path.name}\n", encoding="utf-8")
            return 0

        argv = [
            "--video",
            str(video),
            "--audio",
            str(audio),
            brief_flag,
            str(plan),
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
        return result, calls, stdout.getvalue(), stderr.getvalue(), out_dir

    def seed_brief_flow_inputs(self, root: Path, brief_name: str = "brief.txt", *, brief_text: str = "first brief") -> tuple[Path, Path, Path]:
        video = root / "main.mp4"
        audio = root / "audio.wav"
        brief = root / brief_name
        video.write_bytes(b"video")
        audio.write_bytes(b"audio")
        brief.write_text(brief_text, encoding="utf-8")
        return video, audio, brief

    def test_generic_brief_slug_defaults_to_out_name(self) -> None:
        root = self.make_workspace()
        video, _audio, brief = self.seed_brief_flow_inputs(root, "brief.txt")
        args = pipeline.resolve_args(["--video", str(video), "--brief", str(brief), "--out", str(root / "campaign-run")])

        self.assertEqual(args.brief_slug, "campaign-run")

    def test_non_generic_brief_slug_defaults_to_stem(self) -> None:
        root = self.make_workspace()
        video, _audio, brief = self.seed_brief_flow_inputs(root, "launch-cut.txt")
        args = pipeline.resolve_args(["--video", str(video), "--brief", str(brief), "--out", str(root / "campaign-run")])

        self.assertEqual(args.brief_slug, "launch-cut")

    def invoke_brief_flow(
        self,
        root: Path,
        brief_name: str,
        brief_text: str,
        extra_args: list[str],
    ) -> tuple[int, list[tuple[str, list[str]]], str, str, Path]:
        video, audio, brief = self.seed_brief_flow_inputs(root, brief_name, brief_text=brief_text)
        out_dir = root / "out"
        broll = root / "broll.mp4"
        broll.write_bytes(b"broll")
        calls: list[tuple[str, list[str]]] = []

        def fake_run_step(step: pipeline.Step, cmd: list[str], args) -> int:
            calls.append((step.name, list(cmd)))
            logs_dir = pipeline.log_dir_for_step(step, args)
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / f"{step.name}.log").write_text(f"ran {step.name}\n", encoding="utf-8")
            for sentinel_path in pipeline.sentinel_paths(step, args):
                sentinel_path.parent.mkdir(parents=True, exist_ok=True)
                sentinel_path.write_text(f"{step.name}:{sentinel_path.name}\n", encoding="utf-8")
            return 0

        argv = [
            "--video",
            str(video),
            "--audio",
            str(audio),
            "--brief",
            str(brief),
            "--brief-slug",
            Path(brief_name).stem,
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
        return result, calls, stdout.getvalue(), stderr.getvalue(), out_dir

    def _render_step(self) -> pipeline.Step:
        return pipeline.Step("render", ("hype.mp4",), lambda args: [], per_brief=True)

    def _render_args(self, root: Path) -> tuple[Path, object]:
        out_dir = root / "out"
        brief_dir = out_dir / "briefs" / "brief"
        brief_dir.mkdir(parents=True, exist_ok=True)
        return brief_dir, type("Args", (), {"out": out_dir, "brief_out": brief_dir})()

    def _seed_render_cache(self, root: Path, *, newer: str | None = None) -> tuple[pipeline.Step, object]:
        brief_dir, args = self._render_args(root)
        mtimes = {
            "hype.mp4": 100.0,
            "hype.timeline.json": 90.0,
            "hype.assets.json": 90.0,
            "hype.metadata.json": 90.0,
            "refine.json": 90.0,
        }
        if newer is not None:
            mtimes[newer] = 110.0
        for name, mtime in mtimes.items():
            path = brief_dir / name
            path.write_text(name, encoding="utf-8")
            os.utime(path, (mtime, mtime))
        return self._render_step(), args

    def test_cold_run_with_render_executes_all_steps_and_writes_logs(self) -> None:
        root = self.make_workspace()
        result, calls, _, _, out_dir = self.invoke(root, ["--render"])

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], POOL_RENDER_STEPS)
        source_logs_dir = out_dir / "logs"
        brief_logs_dir = out_dir / "briefs" / "out" / "logs"
        for step_name in ["transcribe", "scenes", "quality_zones", "shots", "triage", "scene_describe", "quote_scout", "pool_build", "pool_merge"]:
            self.assertTrue((source_logs_dir / f"{step_name}.log").is_file())
        for step_name in ["arrange", "cut", "refine", "render", "editor_review", "validate"]:
            self.assertTrue((brief_logs_dir / f"{step_name}.log").is_file())

        commands = dict(calls)
        self.assertEqual(
            commands["transcribe"],
            [
                pipeline.sys.executable,
                str((ROOT / "bin" / "transcribe.py").resolve()),
                "--audio",
                str((root / "audio.wav").resolve()),
                "--out",
                str(out_dir.resolve()),
            ],
        )
        self.assertEqual(
            commands["scenes"],
            [
                pipeline.sys.executable,
                str((ROOT / "bin" / "scenes.py").resolve()),
                "--video",
                str((root / "main.mp4").resolve()),
                "--out",
                str((out_dir / "scenes.json").resolve()),
            ],
        )
        self.assertEqual(
            commands["quality_zones"],
            [
                pipeline.sys.executable,
                str((ROOT / "bin" / "quality_zones.py").resolve()),
                str((root / "main.mp4").resolve()),
                "--out",
                str((out_dir / "quality_zones.json").resolve()),
            ],
        )
        self.assertIn("--shots", commands["cut"])
        self.assertEqual(
            commands["render"],
            [
                pipeline.sys.executable,
                str((ROOT / "bin" / "render_remotion.py").resolve()),
                "--timeline",
                str((out_dir / "briefs" / "out" / "hype.timeline.json").resolve()),
                "--assets",
                str((out_dir / "briefs" / "out" / "hype.assets.json").resolve()),
                "--out",
                str((out_dir / "briefs" / "out" / "hype.mp4").resolve()),
                "--theme",
                str((ROOT.parent / "themes" / "banodoco-default" / "theme.json").resolve()),
            ],
        )

    def test_legacy_invocation_uses_ordered_steps_and_not_performer_cli(self) -> None:
        root = self.make_workspace()
        with mock.patch("artagents.performers.cli.main", side_effect=AssertionError("performer CLI should not run")):
            result, calls, _, _, _ = self.invoke(root, [])

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], POOL_NO_RENDER_STEPS)

    def test_performers_list_dispatches_before_required_arguments(self) -> None:
        with mock.patch("artagents.performers.cli.main", return_value=0) as performers_main:
            result = pipeline.main(["performers", "list"])

        self.assertEqual(result, 0)
        performers_main.assert_called_once_with(["list"])

    def test_fully_cached_run_skips_all_steps(self) -> None:
        root = self.make_workspace()
        _, _, _, _, out_dir = self.invoke(root, ["--render"])
        result, calls, _, _, _ = self.invoke(root, ["--render"])

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], ["pool_merge"])
        self.assertTrue((out_dir / "briefs" / "out" / "hype.mp4").exists())

    def test_partial_cache_resume_skips_completed_early_steps(self) -> None:
        root = self.make_workspace()
        out_dir = root / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "transcript.json").write_text("{}", encoding="utf-8")
        (out_dir / "scenes.json").write_text("[]", encoding="utf-8")

        result, calls, _, _, _ = self.invoke(root, ["--render"])

        self.assertEqual(result, 0)
        self.assertEqual(
            [name for name, _ in calls],
            ["quality_zones", "shots", "triage", "scene_describe", "quote_scout", "pool_build", "pool_merge", "arrange", "cut", "refine", "render", "editor_review", "validate"],
        )

    def test_from_scenes_forces_scenes_onward_to_rerun(self) -> None:
        root = self.make_workspace()
        _, _, _, _, out_dir = self.invoke(root, ["--render"])

        result, calls, _, _, _ = self.invoke(root, ["--render", "--from", "scenes"])

        self.assertEqual(result, 0)
        self.assertEqual(
            [name for name, _ in calls],
            ["scenes", "quality_zones", "shots", "triage", "scene_describe", "quote_scout", "pool_build", "pool_merge", "arrange", "cut", "refine", "render", "editor_review", "validate"],
        )
        self.assertTrue((out_dir / "transcript.json").exists())

    def test_render_gate_skips_render_step_without_flag(self) -> None:
        root = self.make_workspace()
        result, calls, _, _, out_dir = self.invoke(root, [])

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], POOL_NO_RENDER_STEPS)
        self.assertNotIn("refine", [name for name, _ in calls])
        self.assertFalse((out_dir / "hype.mp4").exists())

    def test_non_zero_step_exit_returns_code_and_prints_log_tail(self) -> None:
        root = self.make_workspace()
        result, calls, _, stderr, out_dir = self.invoke(root, ["--render"], returncode_by_step={"transcribe": 7})

        self.assertEqual(result, 7)
        self.assertEqual([name for name, _ in calls], ["transcribe"])
        self.assertIn("transcribe: failed; last 40 log lines", stderr)
        self.assertIn("transcribe-line-49", stderr)
        self.assertNotIn("transcribe-line-0", stderr)
        self.assertTrue((out_dir / "logs" / "transcribe.log").is_file())

    def test_partial_cut_output_reruns_cut_and_prints_warning(self) -> None:
        root = self.make_workspace()
        out_dir = root / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in {
            "transcript.json": "{}",
            "scenes.json": "[]",
            "quality_zones.json": "{}",
            "shots.json": "[]",
            "scene_triage.json": "{}",
            "scene_descriptions.json": "{}",
            "quote_candidates.json": "{}",
            "pool.json": "{}",
        }.items():
            (out_dir / name).write_text(payload, encoding="utf-8")
        brief_dir = out_dir / "briefs" / "out"
        brief_dir.mkdir(parents=True, exist_ok=True)
        (brief_dir / "brief.txt").write_text("[]", encoding="utf-8")
        (brief_dir / "arrangement.json").write_text("{}", encoding="utf-8")
        (brief_dir / "hype.timeline.json").write_text("{}", encoding="utf-8")

        result, calls, stdout, _, _ = self.invoke(root, [])

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], ["pool_merge", "cut"])
        self.assertIn("cut: partial prior output detected, rerunning", stdout)
        for sentinel in ["hype.timeline.json", "hype.assets.json", "hype.metadata.json"]:
            self.assertTrue((brief_dir / sentinel).is_file())

    def test_skip_shots_omits_shots_step_and_cut_flag(self) -> None:
        root = self.make_workspace()
        result, calls, _, _, _ = self.invoke(root, ["--skip", "shots"])

        self.assertEqual(result, 0)
        self.assertNotIn("shots", [name for name, _ in calls])
        commands = dict(calls)
        self.assertNotIn("--shots", commands["cut"])

    def test_pool_flow_second_brief_reuses_per_source_cache_and_preserves_first_brief(self) -> None:
        root = self.make_workspace()
        out_dir = root / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in {
            "transcript.json": "{}",
            "scenes.json": "[]",
            "quality_zones.json": "{}",
            "shots.json": "[]",
            "scene_triage.json": "{}",
            "scene_descriptions.json": "{}",
            "quote_candidates.json": "{}",
            "pool.json": "{}",
        }.items():
            (out_dir / name).write_text(payload, encoding="utf-8")

        first_dir = out_dir / "briefs" / "first"
        first_dir.mkdir(parents=True, exist_ok=True)
        first_snapshot: dict[str, str] = {}
        for name, payload in {
            "brief.txt": "first brief\n",
            "arrangement.json": "{\"name\":\"first\"}\n",
            "hype.timeline.json": "{\"timeline\":\"first\"}\n",
            "hype.assets.json": "{\"assets\":\"first\"}\n",
            "hype.metadata.json": "{\"metadata\":\"first\"}\n",
            "refine.json": "{\"refine\":\"first\"}\n",
            "hype.mp4": "first render\n",
            "validation.json": "{\"validation\":\"first\"}\n",
        }.items():
            path = first_dir / name
            path.write_text(payload, encoding="utf-8")
            first_snapshot[name] = path.read_text(encoding="utf-8")

        result, calls, _, _, out_dir = self.invoke_brief_flow(root, "second.txt", "second brief\n", ["--render"])

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], ["pool_merge", "arrange", "cut", "refine", "render", "editor_review", "validate"])
        self.assertNotIn("triage", [name for name, _ in calls])
        self.assertNotIn("scene_describe", [name for name, _ in calls])
        self.assertNotIn("quote_scout", [name for name, _ in calls])
        self.assertNotIn("pool_build", [name for name, _ in calls])

        second_dir = out_dir / "briefs" / "second"
        self.assertTrue((second_dir / "brief.txt").is_file())
        self.assertEqual((second_dir / "brief.txt").read_text(encoding="utf-8"), "second brief\n")
        for name in ["arrangement.json", "hype.timeline.json", "hype.assets.json", "hype.metadata.json", "refine.json", "hype.mp4", "editor_review.json", "validation.json"]:
            self.assertTrue((second_dir / name).is_file())
        for name, expected in first_snapshot.items():
            self.assertEqual((first_dir / name).read_text(encoding="utf-8"), expected)

        commands = dict(calls)
        self.assertEqual(
            commands["arrange"],
            [
                pipeline.sys.executable,
                str((ROOT / "bin" / "arrange.py").resolve()),
                "--pool",
                str((out_dir / "pool.json").resolve()),
                "--brief",
                str((second_dir / "brief.txt").resolve()),
                "--out",
                str(second_dir.resolve()),
                "--source-slug",
                "out",
                "--brief-slug",
                "second",
            ],
        )
        self.assertIn(str((second_dir / "arrangement.json").resolve()), commands["cut"])
        self.assertEqual(
            commands["refine"],
            [
                pipeline.sys.executable,
                str((ROOT / "bin" / "refine.py").resolve()),
                "--arrangement",
                str((second_dir / "arrangement.json").resolve()),
                "--pool",
                str((out_dir / "pool.json").resolve()),
                "--timeline",
                str((second_dir / "hype.timeline.json").resolve()),
                "--assets",
                str((second_dir / "hype.assets.json").resolve()),
                "--metadata",
                str((second_dir / "hype.metadata.json").resolve()),
                "--transcript",
                str((out_dir / "transcript.json").resolve()),
                "--out",
                str(second_dir.resolve()),
                "--primary-asset",
                "broll",
            ],
        )
        self.assertEqual(
            commands["render"],
            [
                pipeline.sys.executable,
                str((ROOT / "bin" / "render_remotion.py").resolve()),
                "--timeline",
                str((second_dir / "hype.timeline.json").resolve()),
                "--assets",
                str((second_dir / "hype.assets.json").resolve()),
                "--out",
                str((second_dir / "hype.mp4").resolve()),
                "--theme",
                str((ROOT.parent / "themes" / "banodoco-default" / "theme.json").resolve()),
            ],
        )
        self.assertEqual(
            commands["validate"],
            [
                pipeline.sys.executable,
                str((ROOT / "bin" / "validate.py").resolve()),
                "--video",
                str((second_dir / "hype.mp4").resolve()),
                "--timeline",
                str((second_dir / "hype.timeline.json").resolve()),
                "--metadata",
                str((second_dir / "hype.metadata.json").resolve()),
                "--out",
                str((second_dir / "validation.json").resolve()),
            ],
        )

    def test_refine_reruns_when_cut_sentinels_newer(self) -> None:
        root = self.make_workspace()
        result, calls, _, _, out_dir = self.invoke_brief_flow(root, "brief.txt", "brief\n", ["--render"])

        self.assertEqual(result, 0)
        self.assertEqual(
            [name for name, _ in calls],
            POOL_RENDER_STEPS,
        )

        brief_dir = out_dir / "briefs" / "brief"
        refine_path = brief_dir / "refine.json"
        timeline_path = brief_dir / "hype.timeline.json"
        newer = refine_path.stat().st_mtime + 10
        os.utime(timeline_path, (newer, newer))

        result, calls, _, _, _ = self.invoke_brief_flow(root, "brief.txt", "brief\n", ["--render"])

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], ["pool_merge", "refine", "render", "editor_review"])

        result, calls, _, _, _ = self.invoke_brief_flow(root, "brief.txt", "brief\n", ["--render", "--from", "cut"])

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], ["pool_merge", "cut", "refine", "render", "editor_review", "validate"])

    def test_should_rerun_render_when_timeline_newer_than_mp4(self) -> None:
        root = self.make_workspace()
        step, args = self._seed_render_cache(root, newer="hype.timeline.json")

        self.assertTrue(pipeline.should_rerun(step, args, forced=False))

    def test_should_rerun_render_when_assets_newer_than_mp4(self) -> None:
        root = self.make_workspace()
        step, args = self._seed_render_cache(root, newer="hype.assets.json")

        self.assertTrue(pipeline.should_rerun(step, args, forced=False))

    def test_should_rerun_render_when_metadata_newer_than_mp4(self) -> None:
        root = self.make_workspace()
        step, args = self._seed_render_cache(root, newer="hype.metadata.json")

        self.assertTrue(pipeline.should_rerun(step, args, forced=False))

    def test_should_rerun_render_when_refine_newer_than_mp4(self) -> None:
        root = self.make_workspace()
        step, args = self._seed_render_cache(root, newer="refine.json")

        self.assertTrue(pipeline.should_rerun(step, args, forced=False))

    def test_should_rerun_render_returns_false_when_mp4_is_newest(self) -> None:
        root = self.make_workspace()
        step, args = self._seed_render_cache(root)

        self.assertFalse(pipeline.should_rerun(step, args, forced=False))

    def test_refine_skipped_when_render_disabled(self) -> None:
        root = self.make_workspace()
        result, calls, _, _, _ = self.invoke_brief_flow(root, "brief.txt", "brief\n", [])

        self.assertEqual(result, 0)
        self.assertEqual(
            [name for name, _ in calls],
            ["transcribe", "scenes", "quality_zones", "shots", "triage", "scene_describe", "quote_scout", "pool_build", "pool_merge", "arrange", "cut"],
        )
        self.assertNotIn("refine", [name for name, _ in calls])

    def test_plan_emits_deprecation_warning_and_pool_flow_still_runs(self) -> None:
        root = self.make_workspace()
        with self.assertWarns(DeprecationWarning):
            result, calls, _, _, _ = self.invoke(root, [], brief_flag="--plan")

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], POOL_NO_RENDER_STEPS)
        self.assertNotIn("refine", [name for name, _ in calls])

    # Expected failure per prior megaplan scope: this preserves the old legacy
    # call-order assertion as an explicit OOS marker while the active path is pool mode.
    @unittest.expectedFailure
    def test_legacy_plan_call_order_oos_expected_failure(self) -> None:
        root = self.make_workspace()
        with self.assertWarns(DeprecationWarning):
            result, calls, _, _, _ = self.invoke(root, [], brief_flag="--plan")

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], ["transcribe", "scenes", "quality_zones", "shots", "picks", "cut"])

    # Expected failure per prior megaplan scope: legacy render call order is no
    # longer production behavior and is intentionally not restored.
    @unittest.expectedFailure
    def test_legacy_plan_render_call_order_oos_expected_failure(self) -> None:
        root = self.make_workspace()
        with self.assertWarns(DeprecationWarning):
            result, calls, _, _, _ = self.invoke(root, ["--render"], brief_flag="--plan")

        self.assertEqual(result, 0)
        self.assertEqual([name for name, _ in calls], ["transcribe", "scenes", "quality_zones", "shots", "picks", "cut", "render"])


if __name__ == "__main__":
    unittest.main()
