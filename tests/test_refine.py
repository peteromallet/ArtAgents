import json
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from astrid.packs.builtin.cut import run as cut
from astrid.packs.builtin.refine import run as refine
from astrid import timeline
from astrid.packs.builtin.validate import run as validate
from astrid.domains.hype.arrangement_rules import TRIM_BOUND_EXTENSION_SEC


class RefineTest(unittest.TestCase):
    maxDiff = None

    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="refine-tests-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def build_case(
        self,
        *,
        durations: list[float] | None = None,
        first_trim: tuple[float, float] | None = None,
        first_segments: list[tuple[float, float, str]] | None = None,
        first_pool_text: str = "the clean quote",
        speakers: list[str | None] | None = None,
        visual_sources: dict[int, dict[str, object]] | None = None,
        extra_pool_entries: list[dict[str, object]] | None = None,
        quality_zones: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        root = self.make_tempdir()
        out_dir = root / "out"
        brief_out = out_dir / "briefs" / "brief"
        out_dir.mkdir(parents=True, exist_ok=True)
        brief_out.mkdir(parents=True, exist_ok=True)
        media_path = out_dir / "main.mp4"
        media_path.write_bytes(b"video")

        durations = list(durations or [8.0] * 9)
        first_segments = list(
            first_segments
            or [
                (0.0, 2.0, "Intro."),
                (2.0, 7.0, "the clean quote"),
                (7.0, 12.0, "Outro."),
            ]
        )
        first_trim = first_trim or (2.0, 2.0 + durations[0])

        entries: list[dict[str, object]] = []
        clips: list[dict[str, object]] = []
        transcript_segments: list[dict[str, object]] = []
        scenes: list[dict[str, object]] = []
        segment_index = 0
        visual_sources = dict(visual_sources or {})

        for order, duration in enumerate(durations, start=1):
            src_start = float((order - 1) * 15.0)
            src_end = src_start + 12.0
            entry_id = f"pool_d_{order:04d}"
            if order == 1:
                segment_ids: list[int] = []
                for rel_start, rel_end, text in first_segments:
                    transcript_segments.append(
                        {
                            "start": round(src_start + rel_start, 6),
                            "end": round(src_start + rel_end, 6),
                            "text": text,
                        }
                    )
                    segment_ids.append(segment_index)
                    segment_index += 1
                trim_start, trim_end = first_trim
                pool_text = first_pool_text
            else:
                filler_text = f"filler quote {order}"
                transcript_segments.append(
                    {
                        "start": round(src_start + 2.0, 6),
                        "end": round(src_start + 2.0 + duration, 6),
                        "text": f"{filler_text}.",
                    }
                )
                segment_ids = [segment_index]
                segment_index += 1
                trim_start, trim_end = 2.0, 2.0 + duration
                pool_text = filler_text
            entries.append(
                {
                    "id": entry_id,
                    "kind": "source",
                    "category": "dialogue",
                    "asset": "main",
                    "src_start": round(src_start, 6),
                    "src_end": round(src_end, 6),
                    "duration": round(src_end - src_start, 6),
                    "source_ids": {"segment_ids": segment_ids},
                    "scores": {"quotability": 1.0},
                    "excluded": False,
                    "text": pool_text,
                    "speaker": speakers[order - 1] if speakers is not None else "Host",
                    "quote_kind": "hook",
                }
            )
            clips.append(
                {
                    "order": order,
                    "uuid": f"{order:08x}",
                    "audio_source": {
                        "pool_id": entry_id,
                        "trim_sub_range": [round(src_start + trim_start, 6), round(src_start + trim_end, 6)],
                    },
                    "visual_source": dict(visual_sources[order]) if order in visual_sources else None,
                    "rationale": f"clip {order}",
                }
            )
            scenes.append(
                {
                    "index": order,
                    "start": round(src_start, 6),
                    "end": round(src_end, 6),
                    "duration": round(src_end - src_start, 6),
                }
            )
        if extra_pool_entries:
            entries.extend(dict(entry) for entry in extra_pool_entries)

        pool = {
            "version": timeline.POOL_VERSION,
            "generated_at": "2026-04-22T12:00:00Z",
            "source_slug": "source",
            "entries": entries,
        }
        arrangement = {
            "version": timeline.ARRANGEMENT_VERSION,
            "generated_at": "2026-04-22T12:05:00Z",
            "brief_text": "test brief",
            "target_duration_sec": round(min(90.0, max(75.0, sum(durations))), 6),
            "source_slug": "source",
            "brief_slug": "brief",
            "pool_sha256": "a" * 64,
            "brief_sha256": "b" * 64,
            "clips": clips,
        }
        registry = {
            "assets": {
                "main": {
                    "file": str(media_path.resolve()),
                    "type": "video",
                    "duration": 300.0,
                    "resolution": "1920x1080",
                    "fps": 30.0,
                }
            }
        }
        transcript_path = out_dir / "transcript.json"
        scenes_path = out_dir / "scenes.json"
        shots_path = out_dir / "shots.json"
        quality_zones_path = out_dir / "quality_zones.json"
        pool_path = out_dir / "pool.json"
        arrangement_path = brief_out / "arrangement.json"
        assets_path = brief_out / "hype.assets.json"
        timeline_path = brief_out / "hype.timeline.json"
        metadata_path = brief_out / "hype.metadata.json"

        transcript_path.write_text(json.dumps({"segments": transcript_segments}, indent=2) + "\n", encoding="utf-8")
        scenes_path.write_text(json.dumps(scenes, indent=2) + "\n", encoding="utf-8")
        shots_path.write_text("[]\n", encoding="utf-8")
        quality_zones_path.write_text(
            json.dumps({"source_sha256": "d" * 64, "asset_key": "main", "zones": list(quality_zones or [])}, indent=2) + "\n",
            encoding="utf-8",
        )
        timeline.save_pool(pool, pool_path)
        timeline.save_arrangement(arrangement, arrangement_path, {entry["id"] for entry in entries})
        timeline.save_registry(registry, assets_path)

        args = Namespace(
            out=brief_out,
            scenes=scenes_path,
            transcript=transcript_path,
            shots=shots_path,
            renderer="remotion",
            arrangement=arrangement_path,
        )
        compiled_plan = cut.compile_arrangement_plan(arrangement, pool)
        timeline_config = cut.build_multitrack_timeline(arrangement, pool, registry, "main", compiled_plan=compiled_plan, theme_slug="banodoco-default")
        metadata = cut.build_metadata_from_arrangement(
            arrangement,
            pool,
            registry,
            {"main": {"codec": "h264"}},
            args,
            "main",
            transcript_segments,
            quality_zones_ref=quality_zones_path,
            pool_sha256="a" * 64,
            arrangement_sha256="c" * 64,
            brief_sha256="b" * 64,
            compiled_plan=compiled_plan,
        )
        timeline.save_timeline(timeline_config, timeline_path)
        timeline.save_metadata(metadata, metadata_path)

        return {
            "root": root,
            "out_dir": out_dir,
            "brief_out": brief_out,
            "pool": pool,
            "arrangement": arrangement,
            "registry": registry,
            "transcript_segments": transcript_segments,
            "pool_path": pool_path,
            "arrangement_path": arrangement_path,
            "assets_path": assets_path,
            "timeline_path": timeline_path,
            "metadata_path": metadata_path,
            "transcript_path": transcript_path,
            "scenes_path": scenes_path,
            "shots_path": shots_path,
            "quality_zones_path": quality_zones_path,
        }

    def make_visual_entry(
        self,
        entry_id: str,
        *,
        asset: str = "main",
        src_start: float = 100.0,
        src_end: float = 101.0,
    ) -> dict[str, object]:
        return {
            "id": entry_id,
            "kind": "source",
                    "category": "visual",
            "asset": asset,
            "src_start": src_start,
            "src_end": src_end,
            "duration": round(src_end - src_start, 6),
            "source_ids": {"scene_id": "scene_overlay"},
            "scores": {"triage": 0.8, "deep": 0.9},
            "excluded": False,
            "subject": "audience wide",
            "motion_tags": ["crowd"],
            "mood_tags": ["warm"],
            "camera": "wide",
        }

    def run_refine(
        self,
        case: dict[str, object],
        transcriber,
        *,
        max_iterations: int = 3,
        extra_args: list[str] | None = None,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
        argv = [
            "--arrangement",
            str(case["arrangement_path"]),
            "--pool",
            str(case["pool_path"]),
            "--timeline",
            str(case["timeline_path"]),
            "--assets",
            str(case["assets_path"]),
            "--metadata",
            str(case["metadata_path"]),
            "--transcript",
            str(case["transcript_path"]),
            "--out",
            str(case["brief_out"]),
            "--skip-whisper",
            "--max-iterations",
            str(max_iterations),
            *(extra_args or []),
        ]
        self.assertEqual(refine.main(argv, transcriber=transcriber), 0)
        report = json.loads((Path(case["brief_out"]) / "refine.json").read_text(encoding="utf-8"))
        arrangement = timeline.load_arrangement(Path(case["arrangement_path"]), {entry["id"] for entry in case["pool"]["entries"]})
        timeline_json = json.loads(Path(case["timeline_path"]).read_text(encoding="utf-8"))
        metadata = json.loads(Path(case["metadata_path"]).read_text(encoding="utf-8"))
        return report, arrangement, timeline_json, metadata

    def test_detect_half_word_start(self) -> None:
        issues = refine.detect_issues(
            "world peace",
            "orld peace",
            "hello",
            "after",
            True,
            True,
            "orld",
            "peace",
        )
        self.assertIn("half_word_start", issues)

    def test_detect_mid_sentence_cutoff(self) -> None:
        with self.subTest("missing punctuation at both edges"):
            issues = refine.detect_issues(
                "the clean quote",
                "the clean quote",
                "before",
                "after",
                False,
                False,
                "the",
                "quote",
            )
            self.assertIn("mid_sentence_start", issues)
            self.assertIn("mid_sentence_end", issues)
        with self.subTest("punctuated boundaries stay clean"):
            issues = refine.detect_issues(
                "the clean quote",
                "the clean quote",
                "before",
                "after",
                True,
                True,
                "the",
                "quote",
            )
            self.assertNotIn("mid_sentence_start", issues)
            self.assertNotIn("mid_sentence_end", issues)

    def test_detect_boilerplate_end(self) -> None:
        trailing_um = refine.detect_issues(
            "the clean quote",
            "the clean quote um",
            "before",
            "after",
            True,
            True,
            "the",
            "um",
        )
        self.assertIn("boilerplate_end", trailing_um)

        mid_clause_um = refine.detect_issues(
            "the um clean quote",
            "the um clean quote",
            "before",
            "after",
            True,
            True,
            "the",
            "quote",
        )
        self.assertNotIn("boilerplate_end", mid_clause_um)

        like_boundary = refine.detect_issues(
            "like the clean quote",
            "like the clean quote",
            "before",
            "after",
            True,
            True,
            "like",
            "quote",
        )
        so_boundary = refine.detect_issues(
            "so the clean quote",
            "so the clean quote",
            "before",
            "after",
            True,
            True,
            "so",
            "quote",
        )
        self.assertNotIn("boilerplate_start", like_boundary)
        self.assertNotIn("boilerplate_start", so_boundary)

    def test_propose_nudge_allows_extension_past_pool_bounds(self) -> None:
        proposal = refine.propose_nudge(
            ["mid_sentence_start"],
            5.3,
            10.3,
            {"src_start": 5.0, "src_end": 11.0},
            "primary",
            1,
            max_iterations=2,
            min_nudge_sec=0.08,
            max_nudge_sec=TRIM_BOUND_EXTENSION_SEC,
        )
        self.assertIsNotNone(proposal)
        self.assertLess(proposal["trim_after"][0], 5.0)
        self.assertEqual(proposal["trim_after"][0], 4.7)

    def test_propose_nudge_respects_role_duration(self) -> None:
        proposal = refine.propose_nudge(
            ["boilerplate_end"],
            0.0,
            4.0,
            {"src_start": 0.0, "src_end": 5.0},
            "primary",
            0,
            max_iterations=3,
            min_nudge_sec=0.08,
            max_nudge_sec=0.6,
        )
        self.assertIsNone(proposal)

    def test_propose_nudge_still_rejects_beyond_extension(self) -> None:
        lower_bound = 5.0 - TRIM_BOUND_EXTENSION_SEC
        proposal = refine.propose_nudge(
            ["mid_sentence_start"],
            lower_bound,
            9.4,
            {"src_start": 5.0, "src_end": 11.0},
            "primary",
            1,
            max_iterations=2,
            min_nudge_sec=0.08,
            max_nudge_sec=TRIM_BOUND_EXTENSION_SEC,
        )
        self.assertIsNone(proposal)

    def test_refine_loop_converges(self) -> None:
        case = self.build_case(
            durations=[5.0] + [8.5] * 8,
            first_trim=(2.0, 7.0),
            first_segments=[(0.0, 2.0, "Intro."), (2.0, 7.0, "the clean quote."), (7.0, 12.0, "Outro.")],
        )

        def transcriber(_asset_path: Path, start: float, _end: float) -> str:
            if start >= 15.0:
                return f"filler quote {int(start // 15.0) + 1}"
            return "um you know the clean quote" if start < 2.08 else "the clean quote"

        report, arrangement, _, _ = self.run_refine(case, transcriber)
        clip_report = report["auto_fixes"]["audio_boundary"][0]
        self.assertTrue(report["converged"])
        self.assertIn(report["iterations_run"], (1, 2))
        self.assertEqual(arrangement["clips"][0]["audio_source"]["trim_sub_range"], [2.08, 7.0])
        self.assertEqual(clip_report["trim_after"], [2.08, 7.0])
        self.assertEqual(clip_report["similarity_after"], 1.0)
        self.assertEqual(report["per_clip"], report["auto_fixes"]["audio_boundary"])

    def test_refine_loop_bails_on_iteration_cap(self) -> None:
        case = self.build_case(
            durations=[4.0] + [8.5] * 8,
            first_trim=(2.0, 6.0),
            first_segments=[(0.0, 2.0, "Intro."), (2.0, 6.0, "the clean quote."), (6.0, 12.0, "Outro.")],
        )

        def transcriber(_asset_path: Path, start: float, _end: float) -> str:
            if start >= 15.0:
                return f"filler quote {int(start // 15.0) + 1}"
            return "um the clean quote"

        report, arrangement, _, _ = self.run_refine(case, transcriber, max_iterations=3)
        self.assertFalse(report["converged"])
        self.assertEqual(report["iterations_run"], 3)
        self.assertEqual(arrangement["clips"][0]["audio_source"]["trim_sub_range"], [2.0, 6.0])
        self.assertTrue(all(entry["reason"] == "no_valid_nudge" for entry in report["rejected_nudges"]))
        self.assertEqual(report["auto_fixes"]["audio_boundary"], [])

    def test_refine_preserves_total_duration_bounds(self) -> None:
        case = self.build_case(
            durations=[8.0] + [8.695] * 10,
            first_trim=(2.0, 10.0),
            first_segments=[(0.0, 10.0, "the clean quote keeps going"), (10.0, 12.0, "after words")],
            first_pool_text="the clean quote keeps going",
        )

        def transcriber(_asset_path: Path, _start: float, _end: float) -> str:
            return "the clean quote keeps going"

        report, arrangement, _, _ = self.run_refine(case, transcriber, max_iterations=1)
        self.assertEqual(arrangement["clips"][0]["audio_source"]["trim_sub_range"], [2.0, 10.0])
        self.assertTrue(any(entry["reason"] == "total_duration_bounds" for entry in report["rejected_nudges"]))

    def test_refine_report_splits_auto_fixes_and_flags(self) -> None:
        case = self.build_case(
            durations=[5.0] + [8.5] * 8,
            first_trim=(2.0, 7.0),
            first_segments=[(0.0, 2.0, "Intro."), (2.0, 7.0, "the clean quote."), (7.0, 12.0, "Outro.")],
            visual_sources={1: {"pool_id": "pool_v_overlay", "role": "overlay"}},
            extra_pool_entries=[self.make_visual_entry("pool_v_overlay", src_start=100.0, src_end=103.0)],
            quality_zones=[{"kind": "video_dead", "start": 0.0, "end": 10.0}],
        )

        def transcriber(_asset_path: Path, start: float, _end: float) -> str:
            if start >= 15.0:
                return f"filler quote {int(start // 15.0) + 1}"
            return "um you know the clean quote" if start < 2.08 else "the clean quote"

        report, _, _, _ = self.run_refine(case, transcriber)
        self.assertIn("audio_boundary", report["auto_fixes"])
        self.assertEqual(sorted(report["flags"]), ["overlay_fit", "speaker_flow", "visual_quality"])
        self.assertTrue(report["auto_fixes"]["audio_boundary"])
        self.assertEqual(report["auto_fixes"]["audio_boundary"][0]["uuid"], "00000001")
        self.assertIsInstance(report["flags"]["visual_quality"], list)
        self.assertTrue(report["flags"]["overlay_fit"])
        self.assertTrue(report["flags"]["speaker_flow"])
        for findings in report["flags"].values():
            for finding in findings:
                self.assertIn("uuid", finding)
        self.assertEqual(report["per_clip"], report["auto_fixes"]["audio_boundary"])

    def test_refine_writeback_regenerates_timeline_from_cut_helpers(self) -> None:
        case = self.build_case(
            durations=[5.0] + [8.5] * 8,
            first_trim=(2.0, 7.0),
            first_segments=[(0.0, 2.0, "Intro."), (2.0, 7.0, "the clean quote"), (7.0, 12.0, "Outro.")],
        )

        def transcriber(_asset_path: Path, start: float, _end: float) -> str:
            return "um you know the clean quote" if start < 2.08 else "the clean quote"

        self.run_refine(case, transcriber)
        arrangement = timeline.load_arrangement(Path(case["arrangement_path"]), {entry["id"] for entry in case["pool"]["entries"]})
        expected = cut.build_multitrack_timeline(arrangement, case["pool"], case["registry"], "main", theme_slug="banodoco-default")
        expected_path = Path(case["brief_out"]) / "expected.timeline.json"
        timeline.save_timeline(expected, expected_path)
        self.assertEqual(Path(case["timeline_path"]).read_text(encoding="utf-8"), expected_path.read_text(encoding="utf-8"))

    def test_refine_narrows_source_transcript_text(self) -> None:
        case = self.build_case(
            durations=[5.3] + [8.5] * 8,
            first_trim=(2.35, 7.65),
            first_segments=[(0.0, 2.4, "Lead in."), (2.4, 7.6, "the clean quote."), (8.0, 12.0, "tail line.")],
        )

        def transcriber(_asset_path: Path, start: float, _end: float) -> str:
            if start >= 15.0:
                return f"filler quote {int(start // 15.0) + 1}"
            if start < 2.41:
                return "um the clean quote"
            return "the clean quote"

        _, _, _, metadata = self.run_refine(case, transcriber)
        self.assertEqual(metadata["clips"]["clip_a_1"]["source_transcript_text"], "the clean quote.")

    def test_refine_regenerates_quality_zones_metadata(self) -> None:
        case = self.build_case()

        def transcriber(_asset_path: Path, _start: float, _end: float) -> str:
            return "the clean quote"

        _, _, _, metadata = self.run_refine(case, transcriber, max_iterations=1)
        source_meta = metadata["sources"]["main"]
        self.assertEqual(source_meta["quality_zones_ref"], str(Path(case["quality_zones_path"]).resolve()))
        self.assertIn("quality_zones", metadata["pipeline"]["steps_run"])

    def test_refine_audio_boundary_is_idempotent_on_second_run(self) -> None:
        case = self.build_case(
            durations=[5.0] + [8.5] * 8,
            first_trim=(2.0, 7.0),
            first_segments=[(0.0, 2.0, "Intro."), (2.0, 7.0, "the clean quote."), (7.0, 12.0, "Outro.")],
        )

        def transcriber(_asset_path: Path, start: float, _end: float) -> str:
            if start >= 15.0:
                return f"filler quote {int(start // 15.0) + 1}"
            return "um you know the clean quote" if start < 2.08 else "the clean quote"

        first_report, _, _, _ = self.run_refine(case, transcriber)
        second_report, _, _, _ = self.run_refine(case, transcriber)
        self.assertTrue(first_report["auto_fixes"]["audio_boundary"])
        self.assertEqual(second_report["auto_fixes"]["audio_boundary"], [])
        self.assertEqual(second_report["per_clip"], [])

    def test_refine_uses_scoped_transcript_text_as_convergence_target(self) -> None:
        case = self.build_case(
            durations=[5.0] + [8.5] * 8,
            first_trim=(2.5, 7.5),
            first_segments=[(0.0, 2.5, "Transcript lead."), (2.5, 7.5, "Transcript middle."), (7.5, 12.0, "Transcript tail.")],
            first_pool_text="the clean quote",
        )

        def transcriber(_asset_path: Path, start: float, _end: float) -> str:
            if start >= 15.0:
                return f"filler quote {int(start // 15.0) + 1}"
            return "the clean quote"

        report, arrangement, _, _ = self.run_refine(case, transcriber, max_iterations=1)
        self.assertFalse(report["converged"])
        self.assertEqual(report["auto_fixes"]["audio_boundary"], [])
        self.assertEqual(report["per_clip"], [])
        self.assertEqual(arrangement["clips"][0]["audio_source"]["trim_sub_range"], [2.5, 7.5])

    def test_refine_speaker_flow_skips_none_speakers(self) -> None:
        case = self.build_case(
            durations=[5.0] + [8.5] * 8,
            speakers=[None] * 9,
        )

        def transcriber(_asset_path: Path, start: float, _end: float) -> str:
            return f"filler quote {int(start // 15.0) + 1}" if start >= 15.0 else "the clean quote"

        report, _, _, _ = self.run_refine(case, transcriber, max_iterations=1)
        self.assertEqual(report["flags"]["speaker_flow"], [])

    def test_schema_contract_roundtrip(self) -> None:
        case = self.build_case()

        def transcriber(_asset_path: Path, _start: float, _end: float) -> str:
            return "the clean quote"

        _, _, _, metadata = self.run_refine(case, transcriber, max_iterations=1)
        loaded_timeline = timeline.load_timeline(Path(case["timeline_path"]))
        roundtrip_path = Path(case["brief_out"]) / "roundtrip.timeline.json"
        timeline.save_timeline(loaded_timeline, roundtrip_path)
        self.assertEqual(Path(case["timeline_path"]).read_text(encoding="utf-8"), roundtrip_path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(metadata["clips"]), sorted(clip["id"] for clip in loaded_timeline["clips"]))

    def test_validate_compat(self) -> None:
        case = self.build_case(
            durations=[5.0] + [8.5] * 8,
            first_trim=(2.0, 7.0),
            first_segments=[(0.0, 2.0, "Intro."), (2.0, 7.0, "the clean quote"), (7.0, 12.0, "Outro.")],
        )

        def transcriber(_asset_path: Path, start: float, _end: float) -> str:
            if start >= 15.0:
                return f"filler quote {int(start // 15.0) + 1}"
            return "um you know the clean quote" if start < 2.08 else "the clean quote"

        _, _, timeline_json, metadata = self.run_refine(case, transcriber)
        clip = next(item for item in timeline_json["clips"] if item["id"] == "clip_a_1")
        start = float(clip["at"])
        end = start + validate.clip_timeline_duration_sec(clip)
        fake_rendered_segments = [{"start": start, "end": end, "text": "the clean quote"}]
        actual = validate.joined_text(validate.segments_in_range(fake_rendered_segments, start, end))
        expected = metadata["clips"]["clip_a_1"]["source_transcript_text"]
        similarity = validate.token_set_similarity(expected, actual)
        self.assertGreaterEqual(similarity, 0.5)


if __name__ == "__main__":
    unittest.main()
