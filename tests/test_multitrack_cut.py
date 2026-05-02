import json
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from artagents.executors.cut import run as cut
from artagents import timeline
from artagents.executors.validate import run as validate
from artagents.arrangement_rules import ROLE_DURATION_BOUNDS


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
EXPECTED_VALIDATE_BODY = """    for clip in timeline.get(\"clips\", []):
        clip_id = clip.get(\"id\")
        start = float(clip.get(\"at\", 0.0))
        end = start + clip_timeline_duration_sec(clip)
        clip_meta = (clips_meta.get(clip_id, {}) or {})
        caption_kind = clip_meta.get(\"caption_kind\")
        expected = clip_meta.get(\"source_transcript_text\")

        if caption_kind == \"visual\":
            skipped_visual += 1
            results.append({
                \"clip_id\": clip_id,
                \"timeline_range\": [round(start, 3), round(end, 3)],
                \"status\": \"skipped-visual\",
                \"reason\": \"caption describes imagery, not dialogue\",
            })
            continue

        if not expected:
            skipped += 1
            results.append({
                \"clip_id\": clip_id,
                \"timeline_range\": [round(start, 3), round(end, 3)],
                \"status\": \"skipped\",
                \"reason\": \"no source_transcript_text in metadata\",
            })
            continue

        segs = segments_in_range(segments, start, end)
        actual = joined_text(segs)
        similarity = token_set_similarity(expected, actual)
        # Global fallback: if the expected text shows up elsewhere in the cut,
        # flag that so low-similarity doesn't silently hide misaligned clips.
        expected_tokens = set(tokenize(expected))
        global_hit = bool(expected_tokens) and len(expected_tokens & set(tokenize(full_transcript_text))) / max(1, len(expected_tokens)) >= args.threshold
        status = \"pass\" if similarity >= args.threshold else \"fail\"
        if status == \"pass\":
            passes += 1
        else:
            fails += 1
        entry: dict[str, Any] = {
            \"clip_id\": clip_id,
            \"timeline_range\": [round(start, 3), round(end, 3)],
            \"expected\": expected,
            \"actual\": actual,
            \"similarity\": round(similarity, 3),
            \"status\": status,
        }
        if status == \"fail\" and global_hit:
            entry[\"note\"] = \"expected text appears elsewhere in final transcript; caption may be misaligned to the wrong clip range\"
        elif status == \"fail\" and not global_hit and not expected_tokens:
            entry[\"note\"] = \"expected text has no word tokens (likely a visual description, not dialogue)\"
        elif status == \"fail\" and not global_hit:
            entry[\"note\"] = \"expected text not present anywhere in final transcript; likely a visual-only caption or missing audio\"
        results.append(entry)
"""
SOURCE_CUT_GOLDEN = ROOT / "tests" / "fixtures" / "multitrack_cut" / "hype.timeline.golden.json"


class MultitrackCutTest(unittest.TestCase):
    maxDiff = None

    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="multitrack-cut-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def setUp(self) -> None:
        self.tmp_dir = self.make_tempdir()
        dialogue_texts = {
            1: ["This is the first line", "and it keeps going"],
            2: ["Second hook line"],
            3: ["Third beat keeps momentum"],
            4: ["Fourth beat stays on speaker"],
            5: ["Fifth beat adds detail"],
            6: ["Sixth beat resets energy"],
            7: ["Seventh beat keeps pressure"],
            8: ["Eighth beat lands proof"],
            9: ["Ninth beat closes strong"],
        }
        entries: list[dict] = [
            self._visual_entry("pool_v_0002", asset="broll", src_start=200.0, src_end=208.0)
        ]
        self.transcript = []
        self.scenes = []
        clips: list[dict] = []
        segment_index = 0
        for order in range(1, 10):
            src_start = float((order - 1) * 15.0)
            src_end = src_start + 12.0
            segment_ids: list[int] = []
            cursor = src_start + 2.0
            for text in dialogue_texts[order]:
                self.transcript.append({"start": cursor, "end": cursor + 4.0, "text": text})
                segment_ids.append(segment_index)
                segment_index += 1
                cursor += 4.0
            entries.append(
                self._dialogue_entry(
                    f"pool_d_{order:04d}",
                    src_start=src_start,
                    src_end=src_end,
                    text=" ".join(dialogue_texts[order]) + ".",
                    segment_ids=segment_ids,
                    scene_id=f"scene_{order:03d}",
                )
            )
            clip = {
                "order": order,
                "uuid": f"{order:08x}",
                "audio_source": {"pool_id": f"pool_d_{order:04d}", "trim_sub_range": [src_start + 2.0, src_start + 10.0]},
                "visual_source": None,
                "text_overlay": None,
                "rationale": f"Beat {order} keeps the promo moving.",
            }
            if order == 2:
                clip["visual_source"] = {"pool_id": "pool_v_0002", "role": "overlay"}
            if order == 3:
                clip["text_overlay"] = {"content": "ADOS 2026", "style_preset": "title"}
            clips.append(clip)
            self.scenes.append({"index": order, "start": src_start, "end": src_end, "duration": src_end - src_start})
        self.pool = {
            "version": timeline.POOL_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "source_slug": "ados",
            "entries": entries,
        }
        self.arrangement = {
            "version": timeline.ARRANGEMENT_VERSION,
            "generated_at": "2026-04-21T12:10:00Z",
            "brief_text": "Keep the dialogue spine strong and add one wide b-roll cover.",
            "target_duration_sec": 75.0,
            "source_slug": "ados",
            "brief_slug": "hype",
            "pool_sha256": "poolsha",
            "brief_sha256": "briefsha",
            "clips": clips,
        }
        self.scenes_path = self.tmp_dir / "scenes.json"
        self.transcript_path = self.tmp_dir / "transcript.json"
        self.shots_path = self.tmp_dir / "shots.json"
        self.scenes_path.write_text(json.dumps(self.scenes, indent=2) + "\n", encoding="utf-8")
        self.transcript_path.write_text(json.dumps({"segments": self.transcript}, indent=2) + "\n", encoding="utf-8")
        self.shots_path.write_text("[]\n", encoding="utf-8")
        self.args = Namespace(
            out=self.tmp_dir,
            scenes=self.scenes_path,
            transcript=self.transcript_path,
            shots=self.shots_path,
            renderer="remotion",
            arrangement=self.tmp_dir / "arrangement.json",
        )
        asset_paths = {"main": EXAMPLES / "main.mp4", "broll": EXAMPLES / "broll.mp4"}

        def fake_probe(path: Path) -> dict[str, object]:
            return {
                "duration": 10.0,
                "resolution": "1920x1080",
                "fps": 30.0,
                "codec": "h264",
            }

        with mock.patch.object(cut, "probe_asset", side_effect=fake_probe):
            self.registry, self.sources_meta = cut.build_registry(asset_paths, {}, {"assets": {}}, None)
        self.compiled_plan = cut.compile_arrangement_plan(self.arrangement, self.pool)
        self.timeline_config = cut.build_multitrack_timeline(
            self.arrangement,
            self.pool,
            self.registry,
            "main",
            compiled_plan=self.compiled_plan,
            theme_slug="banodoco-default",
        )
        self.metadata = cut.build_metadata_from_arrangement(
            self.arrangement,
            self.pool,
            self.registry,
            self.sources_meta,
            self.args,
            "main",
            self.transcript,
            quality_zones_ref=None,
            pool_sha256="a" * 64,
            arrangement_sha256="b" * 64,
            brief_sha256="c" * 64,
            compiled_plan=self.compiled_plan,
        )

    def _clip(self, clip_id: str) -> dict:
        return next(clip for clip in self.timeline_config["clips"] if clip["id"] == clip_id)

    def _dialogue_entry(
        self,
        entry_id: str,
        *,
        src_start: float,
        src_end: float,
        text: str,
        segment_ids: list[int],
        scene_id: str,
    ) -> dict:
        return {
            "id": entry_id,
            "kind": "source",
                    "category": "dialogue",
            "asset": "main",
            "src_start": src_start,
            "src_end": src_end,
            "duration": src_end - src_start,
            "source_ids": {"segment_ids": segment_ids, "scene_id": scene_id},
            "scores": {"quotability": 0.9},
            "excluded": False,
            "text": text,
            "speaker": "Host",
            "quote_kind": "hook",
        }

    def _visual_entry(self, entry_id: str, *, asset: str, src_start: float, src_end: float) -> dict:
        return {
            "id": entry_id,
            "kind": "source",
                    "category": "visual",
            "asset": asset,
            "src_start": src_start,
            "src_end": src_end,
            "duration": src_end - src_start,
            "source_ids": {"scene_id": "scene_overlay"},
            "scores": {"triage": 0.8, "deep": 0.9},
            "excluded": False,
            "subject": "audience wide",
            "motion_tags": ["crowd"],
            "mood_tags": ["warm"],
            "camera": "wide",
        }

    def _build_compilable_arrangement(
        self,
        first_clip: dict,
        *,
        first_audio_entry: dict,
        extra_entries: list[dict] | None = None,
    ) -> tuple[dict, dict]:
        entries = [first_audio_entry, *(extra_entries or [])]
        clips = [first_clip]
        clips[0].setdefault("uuid", "00000001")
        for order in range(2, 11):
            src_start = float((order + 20) * 15.0)
            src_end = src_start + 12.0
            entry_id = f"pool_d_fill_{order:04d}"
            entries.append(
                self._dialogue_entry(
                    entry_id,
                    src_start=src_start,
                    src_end=src_end,
                    text=f"Filler quote {order}.",
                    segment_ids=[order],
                    scene_id=f"scene_fill_{order:03d}",
                )
            )
            clips.append(
                {
                    "order": order,
                    "uuid": f"{order:08x}",
                    "audio_source": {"pool_id": entry_id, "trim_sub_range": [src_start + 2.0, src_start + 10.0]},
                    "visual_source": None,
                    "text_overlay": None,
                    "rationale": f"Filler beat {order}.",
                }
            )
        arrangement = {
            "version": timeline.ARRANGEMENT_VERSION,
            "generated_at": "2026-04-21T12:10:00Z",
            "brief_text": "Compile-only fixture.",
            "target_duration_sec": 75.0,
            "source_slug": "ados",
            "brief_slug": "hype",
            "pool_sha256": "poolsha",
            "brief_sha256": "briefsha",
            "clips": clips,
        }
        pool = {
            "version": timeline.POOL_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "source_slug": "ados",
            "entries": entries,
        }
        return arrangement, pool

    def test_emits_three_tracks(self) -> None:
        self.assertEqual([track["id"] for track in self.timeline_config["tracks"]], ["v1", "v2", "a1"])

    def test_text_clip_lands_on_v2(self) -> None:
        clip = self._clip("clip_t_3")
        self.assertEqual(clip["track"], "v2")
        self.assertEqual(clip["clipType"], "text")
        self.assertEqual(clip["text"]["content"], "ADOS 2026")
        self.assertEqual(clip["source_uuid"], "00000003")

    def test_b_roll_v2_volume_zero(self) -> None:
        clip = self._clip("clip_v2_2")
        self.assertEqual(clip["track"], "v2")
        self.assertEqual(clip["volume"], 0.0)
        self.assertEqual(clip["source_uuid"], "00000002")

    def test_timeline_clips_carry_matching_source_uuid(self) -> None:
        expected = {clip["order"]: clip["uuid"] for clip in self.arrangement["clips"]}
        for clip in self.timeline_config["clips"]:
            order = int(str(clip["id"]).rsplit("_", 1)[-1])
            self.assertEqual(clip["source_uuid"], expected[order])

    def test_text_overlay_metadata_routes_through_skipped_visual(self) -> None:
        clip = self._clip("clip_t_3")
        clip_meta = self.metadata["clips"]["clip_t_3"]
        self.assertEqual(clip_meta["caption_kind"], "visual")
        self.assertIsNone(clip_meta["source_transcript_text"])

        results = []
        skipped_visual = 0
        skipped = 0
        passes = 0
        fails = 0
        full_transcript_text = " ".join(segment["text"] for segment in self.transcript)

        with mock.patch.object(validate, "token_set_similarity", side_effect=AssertionError("token similarity should not run for visual captions")):
            for current_clip in [clip]:
                clip_id = current_clip.get("id")
                start = float(current_clip.get("at", 0.0))
                end = start + validate.clip_timeline_duration_sec(current_clip)
                current_meta = (self.metadata["clips"].get(clip_id, {}) or {})
                caption_kind = current_meta.get("caption_kind")
                expected = current_meta.get("source_transcript_text")

                if caption_kind == "visual":
                    skipped_visual += 1
                    results.append(
                        {
                            "clip_id": clip_id,
                            "timeline_range": [round(start, 3), round(end, 3)],
                            "status": "skipped-visual",
                            "reason": "caption describes imagery, not dialogue",
                        }
                    )
                    continue

                if not expected:
                    skipped += 1
                    results.append(
                        {
                            "clip_id": clip_id,
                            "timeline_range": [round(start, 3), round(end, 3)],
                            "status": "skipped",
                            "reason": "no source_transcript_text in metadata",
                        }
                    )
                    continue

                segs = validate.segments_in_range(self.transcript, start, end)
                actual = validate.joined_text(segs)
                similarity = validate.token_set_similarity(expected, actual)
                expected_tokens = set(validate.tokenize(expected))
                global_hit = bool(expected_tokens) and len(expected_tokens & set(validate.tokenize(full_transcript_text))) / max(1, len(expected_tokens)) >= 0.5
                status = "pass" if similarity >= 0.5 else "fail"
                if status == "pass":
                    passes += 1
                else:
                    fails += 1
                entry = {
                    "clip_id": clip_id,
                    "timeline_range": [round(start, 3), round(end, 3)],
                    "expected": expected,
                    "actual": actual,
                    "similarity": round(similarity, 3),
                    "status": status,
                }
                if status == "fail" and global_hit:
                    entry["note"] = "expected text appears elsewhere in final transcript; caption may be misaligned to the wrong clip range"
                elif status == "fail" and not global_hit and not expected_tokens:
                    entry["note"] = "expected text has no word tokens (likely a visual description, not dialogue)"
                elif status == "fail" and not global_hit:
                    entry["note"] = "expected text not present anywhere in final transcript; likely a visual-only caption or missing audio"
                results.append(entry)

        self.assertEqual(skipped_visual, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(passes, 0)
        self.assertEqual(fails, 0)
        self.assertEqual(results[0]["status"], "skipped-visual")

    def test_dialogue_source_transcript_text_joined(self) -> None:
        self.assertEqual(
            self.metadata["clips"]["clip_a_1"]["source_transcript_text"],
            "This is the first line and it keeps going",
        )
        self.assertEqual(self.metadata["clips"]["clip_a_1"]["source_uuid"], "00000001")

    def test_b_roll_source_transcript_text_null(self) -> None:
        self.assertIsNone(self.metadata["clips"]["clip_v2_2"]["source_transcript_text"])
        self.assertIsNone(self.metadata["clips"]["clip_v1_4"]["source_transcript_text"])

    def test_pool_kind_text_sidecar(self) -> None:
        clip_meta = self.metadata["clips"]["clip_t_3"]
        self.assertEqual(clip_meta["pool_kind"], "text")
        self.assertIsNone(clip_meta["pool_id"])
        self.assertEqual(clip_meta["text_overlay_content"], "ADOS 2026")

    def test_pool_provenance_fields(self) -> None:
        provenance = self.metadata["pipeline"]["pool_provenance"]
        self.assertEqual(
            set(provenance),
            {"pool_sha256", "arrangement_sha256", "brief_sha256", "source_slug", "brief_slug"},
        )
        self.assertNotIn("picks_provenance", self.metadata["pipeline"])
        self.assertEqual(provenance["source_slug"], "ados")
        self.assertEqual(provenance["brief_slug"], "hype")

    def test_timeline_roundtrip(self) -> None:
        first = self.tmp_dir / "hype.timeline.json"
        second = self.tmp_dir / "hype.roundtrip.timeline.json"
        timeline.save_timeline(self.timeline_config, first)
        original = first.read_text(encoding="utf-8")
        loaded = timeline.load_timeline(first)
        timeline.save_timeline(loaded, second)
        self.assertEqual(second.read_text(encoding="utf-8"), original)

    def test_source_cut_timeline_matches_golden_without_theme(self) -> None:
        path = self.tmp_dir / "hype.timeline.json"
        timeline.save_timeline(self.timeline_config, path)
        self.assertEqual(path.read_text(encoding="utf-8"), SOURCE_CUT_GOLDEN.read_text(encoding="utf-8"))

    def test_validate_py_keeps_visual_caption_skip(self) -> None:
        lines = Path(validate.__file__).read_text(encoding="utf-8").splitlines()
        body = "\n".join(lines)
        self.assertIn('caption_kind == "visual"', body)
        self.assertIn('"status": "skipped-visual"', body)
        self.assertIn("skipped_no_audio", body)

    def test_compile_arrangement_plan_rejects_short_overlay(self) -> None:
        overlay_id = "pool_v_short"
        arrangement, pool = self._build_compilable_arrangement(
            {
                "order": 1,
                "audio_source": {"pool_id": "pool_d_main", "trim_sub_range": [1.0, 10.0]},
                "visual_source": {"pool_id": overlay_id, "role": "overlay"},
                "text_overlay": None,
                "rationale": "Short overlay should fail.",
            },
            first_audio_entry=self._dialogue_entry(
                "pool_d_main",
                src_start=0.0,
                src_end=12.0,
                text="Main quote.",
                segment_ids=[0],
                scene_id="scene_main",
            ),
            extra_entries=[self._visual_entry(overlay_id, asset="broll", src_start=100.0, src_end=102.67)],
        )

        with self.assertRaises(ValueError) as exc_info:
            cut.compile_arrangement_plan(arrangement, pool)
        message = str(exc_info.exception)
        self.assertIn("clip 1", message)
        self.assertIn("pool_v_short", message)
        self.assertIn("2.67s", message)
        self.assertIn("9.00s audio", message)
        self.assertIn("4.00s", message)

    def test_compile_arrangement_plan_accepts_overlay_minimum_threshold(self) -> None:
        overlay_id = "pool_v_exact"
        with self.subTest("exact_minimum"):
            arrangement, pool = self._build_compilable_arrangement(
                {
                    "order": 1,
                    "audio_source": {"pool_id": "pool_d_main", "trim_sub_range": [1.0, 10.0]},
                    "visual_source": {"pool_id": overlay_id, "role": "overlay"},
                    "text_overlay": None,
                    "rationale": "Exact overlay minimum should pass.",
                },
                first_audio_entry=self._dialogue_entry(
                    "pool_d_main",
                    src_start=0.0,
                    src_end=12.0,
                    text="Main quote.",
                    segment_ids=[0],
                    scene_id="scene_main",
                ),
                extra_entries=[self._visual_entry(overlay_id, asset="broll", src_start=100.0, src_end=104.0)],
            )
            plan = cut.compile_arrangement_plan(arrangement, pool)
            self.assertEqual(plan[0]["overlay_play_duration"], 4.0)

        with self.subTest("short_audio_slot_uses_slot_duration"), mock.patch.dict(
            ROLE_DURATION_BOUNDS,
            {"overlay": (2.0, 10.0)},
            clear=False,
        ):
            arrangement, pool = self._build_compilable_arrangement(
                {
                    "order": 1,
                    "audio_source": {"pool_id": "pool_d_main", "trim_sub_range": [1.0, 4.5]},
                    "visual_source": {"pool_id": overlay_id, "role": "overlay"},
                    "text_overlay": None,
                    "rationale": "Short slots should use the audio duration.",
                },
                first_audio_entry=self._dialogue_entry(
                    "pool_d_main",
                    src_start=0.0,
                    src_end=12.0,
                    text="Main quote.",
                    segment_ids=[0],
                    scene_id="scene_main",
                ),
                extra_entries=[self._visual_entry(overlay_id, asset="broll", src_start=100.0, src_end=103.5)],
            )
            plan = cut.compile_arrangement_plan(arrangement, pool)
            self.assertEqual(plan[0]["overlay_play_duration"], 3.5)

    def test_compile_arrangement_plan_preserves_extended_trim(self) -> None:
        arrangement, pool = self._build_compilable_arrangement(
            {
                "order": 1,
                "audio_source": {"pool_id": "pool_d_main", "trim_sub_range": [4.7, 12.0]},
                "visual_source": None,
                "text_overlay": None,
                "rationale": "Extended trim should survive recompilation.",
            },
            first_audio_entry=self._dialogue_entry(
                "pool_d_main",
                src_start=5.0,
                src_end=12.0,
                text="Extended trim quote.",
                segment_ids=[0],
                scene_id="scene_main",
            ),
        )

        plan = cut.compile_arrangement_plan(arrangement, pool)
        self.assertEqual(plan[0]["audio_trim_start"], 4.7)


if __name__ == "__main__":
    unittest.main()
