from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from astrid.packs.builtin.logo_ideas import run as logo_ideas


class LogoIdeasParserTest(unittest.TestCase):
    def test_build_parser_accepts_expected_flags_and_defaults(self):
        parser = logo_ideas.build_parser()
        self.assertIsInstance(parser, argparse.ArgumentParser)

        args = parser.parse_args(["--ideas", "brand brief", "--out", "/tmp/out"])

        self.assertEqual(args.ideas, "brand brief")
        self.assertEqual(args.out, Path("/tmp/out"))
        self.assertEqual(args.count, logo_ideas.DEFAULT_COUNT)
        self.assertEqual(args.provider, logo_ideas.DEFAULT_PROVIDER)
        self.assertEqual(args.model, logo_ideas.DEFAULT_FIREWORKS_MODEL)
        # default image-size is the preset string, post-type-conversion
        self.assertEqual(args.image_size, logo_ideas.DEFAULT_IMAGE_SIZE)
        self.assertEqual(args.output_format, logo_ideas.DEFAULT_OUTPUT_FORMAT)
        self.assertIsNone(args.env_file)
        self.assertFalse(args.dry_run)

    def test_build_parser_accepts_overrides_for_all_documented_flags(self):
        parser = logo_ideas.build_parser()
        args = parser.parse_args(
            [
                "--ideas",
                "x",
                "--out",
                "/tmp/o",
                "--count",
                "3",
                "--provider",
                "gpt-image",
                "--model",
                "accounts/foo/models/bar",
                "--image-size",
                "512x768",
                "--output-format",
                "webp",
                "--env-file",
                "/tmp/.env",
                "--dry-run",
            ]
        )
        self.assertEqual(args.count, 3)
        self.assertEqual(args.provider, "gpt-image")
        self.assertEqual(args.model, "accounts/foo/models/bar")
        self.assertEqual(args.image_size, {"width": 512, "height": 768})
        self.assertEqual(args.output_format, "webp")
        self.assertEqual(args.env_file, Path("/tmp/.env"))
        self.assertTrue(args.dry_run)


class ParseImageSizeTest(unittest.TestCase):
    def test_accepts_fal_presets(self):
        for preset in ("square_hd", "square", "portrait_4_3", "portrait_16_9", "landscape_4_3", "landscape_16_9"):
            self.assertEqual(logo_ideas.parse_image_size(preset), preset)

    def test_accepts_width_x_height(self):
        self.assertEqual(logo_ideas.parse_image_size("1024x768"), {"width": 1024, "height": 768})
        self.assertEqual(logo_ideas.parse_image_size("  640x480  "), {"width": 640, "height": 480})

    def test_rejects_invalid_inputs(self):
        for bad in ("nope", "0x100", "100x0", "1024", "1024x", "x768", "abcxdef"):
            with self.assertRaises(argparse.ArgumentTypeError):
                logo_ideas.parse_image_size(bad)


class BuildLayoutTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="logo-ideas-test-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def test_creates_root_and_images_dirs(self):
        base = self.make_tempdir()
        target = base / "run-001"
        layout = logo_ideas.build_layout(target)

        self.assertIn("root", layout)
        self.assertIn("images", layout)
        self.assertTrue(layout["root"].is_dir())
        self.assertTrue(layout["images"].is_dir())
        self.assertEqual(layout["images"], layout["root"] / "images")


class ValidateArgsTest(unittest.TestCase):
    def test_rejects_count_less_than_one(self):
        parser = logo_ideas.build_parser()
        with self.assertRaises(SystemExit):
            logo_ideas._validate_args(parser, argparse.Namespace(count=0))

    def test_rejects_count_above_sixty_four(self):
        parser = logo_ideas.build_parser()
        with self.assertRaises(SystemExit):
            logo_ideas._validate_args(parser, argparse.Namespace(count=65))

    def test_accepts_in_range_counts(self):
        parser = logo_ideas.build_parser()
        for value in (1, 9, 64):
            logo_ideas._validate_args(parser, argparse.Namespace(count=value))


def _fireworks_response(concepts):
    return {
        "choices": [
            {"message": {"content": json.dumps({"concepts": concepts})}}
        ]
    }


class ParseConceptsTest(unittest.TestCase):
    def test_extracts_concepts_from_well_formed_response(self):
        concepts = [
            {"name": "Aurora", "rationale": "ethereal", "prompt": "soft gradient mark, pastel"},
            {"name": "Forge", "rationale": "industrial", "prompt": "iron monogram, hammered metal"},
        ]
        result = logo_ideas.parse_concepts(_fireworks_response(concepts), count=5)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["candidate_id"], "logo-001")
        self.assertEqual(result[0]["index"], 1)
        self.assertEqual(result[0]["name"], "Aurora")
        self.assertEqual(result[0]["prompt"], "soft gradient mark, pastel")
        self.assertEqual(result[1]["candidate_id"], "logo-002")

    def test_truncates_to_requested_count(self):
        concepts = [{"name": f"c{i}", "prompt": f"p{i}"} for i in range(5)]
        result = logo_ideas.parse_concepts(_fireworks_response(concepts), count=2)
        self.assertEqual(len(result), 2)

    def test_extracts_json_via_regex_when_response_has_extra_text(self):
        wrapped = (
            'Sure! Here are the concepts:\n'
            '{"concepts":[{"name":"X","prompt":"a circle"}]}\n'
            'Hope this helps!'
        )
        response = {"choices": [{"message": {"content": wrapped}}]}
        result = logo_ideas.parse_concepts(response, count=3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "X")

    def test_rejects_response_without_choices(self):
        with self.assertRaises(SystemExit):
            logo_ideas.parse_concepts({"choices": []}, count=1)

    def test_rejects_missing_concepts_field(self):
        response = {"choices": [{"message": {"content": json.dumps({"foo": "bar"})}}]}
        with self.assertRaises(SystemExit):
            logo_ideas.parse_concepts(response, count=1)

    def test_rejects_empty_concepts_list(self):
        with self.assertRaises(SystemExit):
            logo_ideas.parse_concepts(_fireworks_response([]), count=1)

    def test_rejects_unparseable_response(self):
        response = {"choices": [{"message": {"content": "no json here at all"}}]}
        with self.assertRaises(SystemExit):
            logo_ideas.parse_concepts(response, count=1)

    def test_skips_entries_without_prompts(self):
        concepts = [
            {"name": "no-prompt", "prompt": ""},
            {"name": "valid", "prompt": "round seal in navy"},
        ]
        result = logo_ideas.parse_concepts(_fireworks_response(concepts), count=5)
        # Only the second entry has a prompt; first is skipped, but the index=1 (the iter position)
        # is consumed by the empty entry, so the surviving entry stays at logo-002.
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["candidate_id"], "logo-002")
        self.assertEqual(result[0]["name"], "valid")


class PlannedConceptsTest(unittest.TestCase):
    def test_generates_n_placeholder_concepts_with_padded_ids(self):
        concepts = logo_ideas._planned_concepts("a brand for tea", 3)
        self.assertEqual(len(concepts), 3)
        self.assertEqual([c["candidate_id"] for c in concepts], ["logo-001", "logo-002", "logo-003"])
        for index, concept in enumerate(concepts, start=1):
            self.assertEqual(concept["index"], index)
            self.assertIn("Planned concept", concept["name"])
            self.assertIn("[dry-run]", concept["prompt"])
            self.assertIn("a brand for tea", concept["prompt"])

    def test_zero_count_returns_empty_list(self):
        self.assertEqual(logo_ideas._planned_concepts("x", 0), [])

    def test_id_format_pads_to_three_digits_for_large_counts(self):
        concepts = logo_ideas._planned_concepts("x", 12)
        self.assertEqual(concepts[0]["candidate_id"], "logo-001")
        self.assertEqual(concepts[9]["candidate_id"], "logo-010")
        self.assertEqual(concepts[11]["candidate_id"], "logo-012")


class FalPayloadTest(unittest.TestCase):
    def test_z_image_payload_shape(self):
        payload = logo_ideas._fal_payload("z-image", "a circle", "square_hd", "png")
        self.assertEqual(
            payload,
            {"prompt": "a circle", "image_size": "square_hd", "num_images": 1, "output_format": "png"},
        )

    def test_z_image_passes_through_dict_image_size(self):
        payload = logo_ideas._fal_payload("z-image", "p", {"width": 640, "height": 480}, "webp")
        self.assertEqual(payload["image_size"], {"width": 640, "height": 480})
        self.assertEqual(payload["output_format"], "webp")

    def test_jpg_format_normalises_to_jpeg(self):
        payload = logo_ideas._fal_payload("z-image", "p", "square", "jpg")
        self.assertEqual(payload["output_format"], "jpeg")

    def test_gpt_image_payload_includes_quality_high(self):
        payload = logo_ideas._fal_payload("gpt-image", "a square", "portrait_16_9", "jpeg")
        self.assertEqual(payload["prompt"], "a square")
        self.assertEqual(payload["image_size"], "portrait_16_9")
        self.assertEqual(payload["num_images"], 1)
        self.assertEqual(payload["output_format"], "jpeg")
        self.assertEqual(payload["quality"], "high")

    def test_unknown_provider_raises(self):
        with self.assertRaises(SystemExit):
            logo_ideas._fal_payload("midjourney", "p", "square", "png")


class DryRunSmokeTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="logo-ideas-smoke-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def _patch_network(self):
        boom_post = mock.patch.object(
            logo_ideas, "_http_post_json", side_effect=AssertionError("network call in dry-run")
        )
        boom_get = mock.patch.object(
            logo_ideas, "_http_get_json", side_effect=AssertionError("network call in dry-run")
        )
        boom_get_bytes = mock.patch.object(
            logo_ideas, "_http_get_bytes", side_effect=AssertionError("network call in dry-run")
        )
        boom_env = mock.patch.object(
            logo_ideas, "_load_env_var", side_effect=AssertionError("env lookup in dry-run")
        )
        for patcher in (boom_post, boom_get, boom_get_bytes, boom_env):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_dry_run_default_provider_writes_grid_artifacts_without_network(self):
        out_dir = self.make_tempdir() / "logos"
        self._patch_network()

        rc = logo_ideas.main(
            ["--ideas", "test brief", "--out", str(out_dir), "--count", "2", "--dry-run"]
        )
        self.assertEqual(rc, 0)

        root = out_dir.expanduser().resolve()
        for name in ("logo-plan.json", "concepts.json", "prompts.json", "logo-manifest.json"):
            self.assertTrue((root / name).is_file(), f"missing {name}")

        plan = json.loads((root / "logo-plan.json").read_text())
        self.assertEqual(plan["mode"], "dry-run")
        self.assertEqual(plan["provider"], "gpt-image")

        manifest = json.loads((root / "logo-manifest.json").read_text())
        self.assertEqual(len(manifest["candidates"]), 2)
        # Grid mode: every candidate references the SAME grid image at root.
        grid_path = manifest["grid"]["path"]
        self.assertTrue(grid_path.endswith("/grid.png"), grid_path)
        self.assertEqual(manifest["grid"]["mode"], "single-call")
        for candidate in manifest["candidates"]:
            generated = candidate["generated"]
            self.assertTrue(generated.get("placeholder"))
            self.assertEqual(generated["path"], grid_path)
            self.assertIn("grid_prompt", generated)

    def test_dry_run_z_image_provider_writes_per_concept_artifacts(self):
        out_dir = self.make_tempdir() / "logos"
        self._patch_network()

        rc = logo_ideas.main(
            [
                "--ideas",
                "test brief",
                "--out",
                str(out_dir),
                "--count",
                "2",
                "--provider",
                "z-image",
                "--dry-run",
            ]
        )
        self.assertEqual(rc, 0)

        root = out_dir.expanduser().resolve()
        manifest = json.loads((root / "logo-manifest.json").read_text())
        self.assertEqual(len(manifest["candidates"]), 2)
        for candidate in manifest["candidates"]:
            generated = candidate["generated"]
            self.assertTrue(generated.get("placeholder"))
            self.assertIn("/images/", generated["path"])


if __name__ == "__main__":
    unittest.main()
