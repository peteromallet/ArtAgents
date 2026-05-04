import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from artagents.orchestrators.thumbnail_maker import run as thumbnail_maker


class ThumbnailMakerTest(unittest.TestCase):
    def test_query_planning_detects_source_needs_deterministically(self) -> None:
        plan = thumbnail_maker.plan_evidence_needs("dramatic speaker title on stage")

        self.assertEqual(plan["tokens"], ["dramatic", "on", "speaker", "stage", "title"])
        self.assertEqual(
            [need["id"] for need in plan["needs"]],
            ["speaker_or_person_framing", "scene_context", "title_or_quote_context", "expressive_moment"],
        )

    def test_dry_run_writes_reference_pack_with_composition_crops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(thumbnail_maker.asset_cache, "resolve_input", return_value=Path("/tmp/source.mp4")):
                result = thumbnail_maker.main(
                    [
                        "--video",
                        "/tmp/source.mp4",
                        "--query",
                        "dramatic speaker title thumbnail",
                        "--out",
                        str(root),
                        "--dry-run",
                        "--count",
                        "2",
                    ]
                )

            pack = json.loads((root / "evidence" / "reference-pack.json").read_text(encoding="utf-8"))

        self.assertEqual(result, 0)
        self.assertEqual(pack["composition_crop_policy"]["kind"], "composition_crop")
        self.assertIn("no face, person, or speaker detection is claimed", pack["composition_crop_policy"]["note"])
        self.assertTrue(pack["references"])
        self.assertEqual(pack["references"][0]["composition_crops"][0]["kind"], "composition_crop")
        self.assertFalse(pack["references"][0]["full_frame"]["materialized"])

    def test_dry_run_writes_prompts_manifest_contact_sheet_and_refinement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous.json"
            previous.write_text(
                json.dumps({"candidates": [{"candidate_id": "old-001"}, {"candidate_id": "old-002"}]}),
                encoding="utf-8",
            )
            with mock.patch.object(thumbnail_maker.asset_cache, "resolve_input", return_value=Path("/tmp/source.mp4")):
                result = thumbnail_maker.main(
                    [
                        "--video",
                        "/tmp/source.mp4",
                        "--query",
                        "dramatic speaker title thumbnail",
                        "--out",
                        str(root),
                        "--dry-run",
                        "--count",
                        "3",
                        "--previous-manifest",
                        str(previous),
                        "--feedback",
                        "make the title larger",
                    ]
                )

            prompts = json.loads((root / "prompts" / "prompts.json").read_text(encoding="utf-8"))
            manifest = json.loads((root / "thumbnail-manifest.json").read_text(encoding="utf-8"))
            refinement = json.loads((root / "refinement.json").read_text(encoding="utf-8"))
            contact_sheet_exists = (root / "review" / "contact-sheet.jpg").is_file()
            request_exists = (root / "generated" / "thumb-001.request.json").is_file()

        self.assertEqual(result, 0)
        self.assertEqual([job["candidate_id"] for job in prompts["jobs"]], ["thumb-001", "thumb-002", "thumb-003"])
        self.assertEqual(manifest["size"], "1536x864")
        self.assertEqual(len(manifest["candidates"]), 3)
        self.assertTrue(contact_sheet_exists)
        self.assertTrue(request_exists)
        self.assertEqual(refinement["lineage"][0]["refines_candidate_id"], "old-001")
        self.assertEqual(refinement["lineage"][1]["refines_candidate_id"], "old-002")

    def test_query_selection_normalization_falls_back_for_unparseable_output(self) -> None:
        candidates = [{"candidate_id": "ev-001", "index": 1}, {"candidate_id": "ev-002", "index": 2}]

        selection = thumbnail_maker.normalize_query_selection(
            {"status": "ok", "answer": "not valid json"},
            candidates,
            count=1,
            dry_run=False,
        )

        self.assertTrue(selection["fallback"])
        self.assertEqual(selection["fallback_reason"], "model_output_unparseable")
        self.assertEqual(selection["selected"][0]["candidate_id"], "ev-001")

    def test_candidate_records_sample_across_full_talk_span(self) -> None:
        shots = [
            {
                "scene_index": index,
                "frames": [{"timestamp": float(index), "path": f"scene{index:03d}.jpg"}],
            }
            for index in range(1, 101)
        ]

        candidates = thumbnail_maker._candidate_records(shots, max_candidates=5)

        self.assertEqual([candidate["candidate_id"] for candidate in candidates], ["ev-001", "ev-002", "ev-003", "ev-004", "ev-005"])
        self.assertEqual(candidates[0]["scene_index"], 1)
        self.assertEqual(candidates[-1]["scene_index"], 100)
        self.assertGreater(candidates[2]["scene_index"], 40)

    def test_non_dry_main_resolves_video_before_scene_helpers_with_mocks(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_resolve(value, *, want):
                calls.append("resolve")
                self.assertEqual(want, "path")
                return Path("/tmp/resolved-video.mp4")

            def fake_detect(video_path, threshold):
                calls.append("detect")
                self.assertEqual(video_path, Path("/tmp/resolved-video.mp4"))
                return [{"index": 1, "start": 0.0, "end": 2.0, "duration": 2.0}]

            def fake_generate(argv):
                manifest_path = Path(argv[argv.index("--manifest") + 1])
                out_dir = Path(argv[argv.index("--out-dir") + 1])
                manifest_path.write_text(
                    json.dumps(
                        [
                            {
                                "prompt": "prompt",
                                "outputs": [str(out_dir / "thumb-001.png")],
                                "usage": {"total_tokens": 1},
                            }
                        ]
                    ),
                    encoding="utf-8",
                )
                return 0

            def fake_build_shots(video_path, scenes, out_dir, per_scene):
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                return []

            with (
                mock.patch.object(thumbnail_maker.asset_cache, "resolve_input", side_effect=fake_resolve),
                mock.patch("artagents.packs.builtin.scenes.run.detect_scenes", side_effect=fake_detect),
                mock.patch("artagents.packs.builtin.scenes.run.write_outputs"),
                mock.patch("artagents.packs.builtin.shots.run.build_shots", side_effect=fake_build_shots),
                mock.patch("artagents.packs.builtin.generate_image.run.main", side_effect=fake_generate),
            ):
                result = thumbnail_maker.main(
                    [
                        "--video",
                        "/tmp/source.mp4",
                        "--query",
                        "speaker title",
                        "--out",
                        str(root),
                        "--count",
                        "1",
                    ]
                )

            manifest = json.loads((root / "thumbnail-manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(result, 0)
        self.assertEqual(calls, ["resolve", "detect"])
        self.assertEqual(manifest["candidates"][0]["generated"]["path"], str((root / "generated" / "thumb-001.png").resolve()))

    def test_non_dry_generation_uses_generate_image_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout = thumbnail_maker.build_output_layout(root)
            thumbnail_maker.ensure_output_layout(layout)
            args = thumbnail_maker.build_parser().parse_args(
                [
                    "--video",
                    "/tmp/source.mp4",
                    "--query",
                    "speaker title",
                    "--out",
                    str(root),
                    "--count",
                    "1",
                ]
            )
            plan = {
                "mode": "run",
                "video": {"original": "/tmp/source.mp4", "resolved": "/tmp/source.mp4", "resolved_ok": True},
            }
            reference_pack = {
                "references": [
                    {
                        "candidate_id": "ev-001",
                        "selection_reason": "test evidence",
                        "scene_index": 1,
                        "timestamp_sec": 1.25,
                        "full_frame": {"source_path": "/tmp/frame.jpg"},
                        "composition_crops": [],
                    }
                ]
            }

            def fake_generate(argv):
                (layout["generated"] / "generate-image-manifest.json").write_text(
                    json.dumps(
                        [
                            {
                                "prompt": "prompt",
                                "outputs": [str(layout["generated"] / "thumb-001.png")],
                                "usage": {"total_tokens": 1},
                            }
                        ]
                    ),
                    encoding="utf-8",
                )
                return 0

            with mock.patch("artagents.packs.builtin.generate_image.run.main", side_effect=fake_generate) as generate_main:
                manifest = thumbnail_maker.generate_thumbnail_outputs(args, layout, plan, reference_pack)

        generate_main.assert_called_once()
        self.assertEqual(manifest["generation_returncode"], 0)
        self.assertEqual(manifest["candidates"][0]["generated"]["path"], str(layout["generated"] / "thumb-001.png"))

    def test_generated_contact_sheet_with_pil_images(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed in this environment")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "thumb-001.png"
            Image.new("RGB", (64, 36), (200, 20, 20)).save(image_path)

            sheet = thumbnail_maker._write_final_contact_sheet(
                [{"candidate_id": "thumb-001", "path": str(image_path)}],
                root / "contact-sheet.jpg",
            )

        self.assertEqual(sheet["mode"], "images")
        self.assertEqual(sheet["image_count"], 1)


if __name__ == "__main__":
    unittest.main()
