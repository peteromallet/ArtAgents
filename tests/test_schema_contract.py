import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from artagents import timeline

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
GENERATED_TYPES = ROOT / "remotion" / "src" / "types.generated.ts"
GENERATOR = ROOT / "scripts" / "gen_remotion_types.py"


class SchemaContractTest(unittest.TestCase):
    maxDiff = None

    def _make_tempdir(self, prefix: str) -> Path:
        path = Path(tempfile.mkdtemp(prefix=prefix))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def _roundtrip_timeline(self, path: Path) -> str:
        original = path.read_text(encoding="utf-8")
        config = timeline.load_timeline(path)
        tmp_path = self._make_tempdir("timeline-roundtrip-") / path.name
        timeline.save_timeline(config, tmp_path)
        return tmp_path.read_text(encoding="utf-8"), original

    def _roundtrip_registry(self, path: Path) -> str:
        original = path.read_text(encoding="utf-8")
        registry = timeline.load_registry(path)
        tmp_path = self._make_tempdir("registry-roundtrip-") / path.name
        timeline.save_registry(registry, tmp_path)
        return tmp_path.read_text(encoding="utf-8"), original

    def _parse_generated_array(self, name: str) -> set[str]:
        source = GENERATED_TYPES.read_text(encoding="utf-8")
        pattern = rf"export const {name} = \[(.*?)\] as const;"
        match = re.search(pattern, source, re.DOTALL)
        self.assertIsNotNone(match, f"Missing generated array {name}")
        return set(re.findall(r"'([^']+)'", match.group(1)))

    def test_golden_roundtrip(self) -> None:
        roundtripped_timeline, original_timeline = self._roundtrip_timeline(EXAMPLES / "hype.timeline.json")
        roundtripped_assets, original_assets = self._roundtrip_registry(EXAMPLES / "hype.assets.json")
        self.assertEqual(roundtripped_timeline, original_timeline)
        self.assertEqual(roundtripped_assets, original_assets)

    def test_full_roundtrip(self) -> None:
        roundtripped_timeline, original_timeline = self._roundtrip_timeline(EXAMPLES / "hype.timeline.full.json")
        roundtripped_assets, original_assets = self._roundtrip_registry(EXAMPLES / "hype.assets.full.json")
        self.assertEqual(roundtripped_timeline, original_timeline)
        self.assertEqual(roundtripped_assets, original_assets)

    def test_generator_byte_stability(self) -> None:
        tmp_path = self._make_tempdir("generated-types-") / "types.generated.ts"
        subprocess.run([sys.executable, str(GENERATOR), str(tmp_path)], cwd=ROOT, check=True)
        self.assertEqual(tmp_path.read_text(encoding="utf-8"), GENERATED_TYPES.read_text(encoding="utf-8"))

    def test_generator_arrays_match_frozensets(self) -> None:
        self.assertEqual(self._parse_generated_array("_TIMELINE_TOP_ALLOWED"), set(timeline._TIMELINE_TOP_ALLOWED))
        self.assertEqual(self._parse_generated_array("_THEME_OVERRIDES_ALLOWED"), set(timeline._THEME_OVERRIDES_ALLOWED))
        self.assertEqual(self._parse_generated_array("_CLIP_ALLOWED"), set(timeline._CLIP_ALLOWED))
        self.assertEqual(self._parse_generated_array("_TRACK_ALLOWED"), set(timeline._TRACK_ALLOWED))
        self.assertEqual(self._parse_generated_array("_ASSET_ENTRY_ALLOWED"), set(timeline._ASSET_ENTRY_ALLOWED))

    def test_full_fixture_covers_optional_keys(self) -> None:
        config = timeline.load_timeline(EXAMPLES / "hype.timeline.full.json")
        registry = timeline.load_registry(EXAMPLES / "hype.assets.full.json")

        self.assertIn("generation_defaults", timeline._TIMELINE_TOP_ALLOWED)
        clip_keys = {key for clip in config["clips"] for key in timeline._normalize_clip_for_validation(clip)}
        track_keys = {key for track in config.get("tracks", []) for key in track}
        theme_overrides_keys = set(config.get("theme_overrides") or {})
        asset_entry_keys = {key for entry in registry["assets"].values() for key in entry}

        self.assertEqual(clip_keys, set(timeline._CLIP_ALLOWED))
        self.assertEqual(track_keys, set(timeline._TRACK_ALLOWED))
        self.assertEqual(theme_overrides_keys, set(timeline._THEME_OVERRIDES_ALLOWED))
        self.assertEqual(asset_entry_keys, set(timeline._ASSET_ENTRY_ALLOWED))

        text_keys = set(config["clips"][2]["text"])
        self.assertEqual(
            text_keys,
            {"content", "fontFamily", "fontSize", "color", "align", "bold", "italic"},
        )
        self.assertEqual(
            set(config["clips"][0]["entrance"]),
            {"type", "duration", "intensity", "params"},
        )
        self.assertEqual(
            set(config["clips"][0]["exit"]),
            {"type", "duration", "intensity", "params"},
        )
        self.assertEqual(
            set(config["clips"][0]["continuous"]),
            {"type", "intensity", "params"},
        )
        self.assertEqual(
            set(config["clips"][0]["transition"]),
            {"type", "duration"},
        )
        self.assertEqual(
            set(config["clips"][0]["effects"]),
            {"fade_in", "fade_out"},
        )

    def test_generation_defaults_roundtrip_preserves_nested_object(self) -> None:
        config = {
            "theme": "banodoco-default",
            "theme_overrides": {"visual": {"canvas": {"fps": 24}}},
            "generation_defaults": {
                "model": "sequence-v1",
                "image": {"quality": "high", "provider": "reigh"},
                "provider_settings": {"seed": 1234, "flags": ["keep", "open"]},
            },
            "clips": [],
        }
        path = self._make_tempdir("generation-defaults-") / "timeline.json"

        timeline.save_timeline(config, path)  # type: ignore[arg-type]
        loaded = timeline.load_timeline(path)

        self.assertEqual(loaded["generation_defaults"], config["generation_defaults"])

    def test_generation_defaults_validation_does_not_inspect_inner_keys(self) -> None:
        config = {
            "theme": "banodoco-default",
            "generation_defaults": {
                "model": "sequence-v1",
                "image": {"quality": "high"},
            },
            "clips": [],
        }

        timeline.validate_timeline(config, strict=False)

    def test_validate_timeline_rejects_missing_theme_after_shared_shape_check(self) -> None:
        with self.assertRaisesRegex(ValueError, "Timeline.theme must be a non-empty slug"):
            timeline.validate_timeline({"clips": []}, strict=False)

    def test_effect_params_accept_animation_reference_arrays(self) -> None:
        config = {
            "theme": "banodoco-default",
            "clips": [
                {
                    "id": "title",
                    "at": 0,
                    "track": "v1",
                    "clipType": "text-card",
                    "hold": 2,
                    "params": {
                        "content": "Hello",
                        "entrance": ["fade-up", {"id": "type-on", "durationFrames": 12}],
                        "exit": {"id": "fade", "durationFrames": 8, "params": {"opacity": 0}},
                    },
                }
            ],
        }

        def meta(animation_id: str) -> dict:
            return {
                "fade-up": {"kind": "wrapper", "phase": "entrance"},
                "type-on": {"kind": "hook", "phase": "entrance"},
                "fade": {"kind": "wrapper", "phase": "exit"},
            }[animation_id]

        with (
            mock.patch.object(timeline, "_animation_ids", return_value={"fade-up", "type-on", "fade"}),
            mock.patch.object(timeline, "_animation_meta", side_effect=meta),
        ):
            timeline.validate_timeline(config)

    def test_effect_params_reject_unknown_animation_reference(self) -> None:
        config = {
            "theme": "banodoco-default",
            "clips": [
                {
                    "id": "title",
                    "at": 0,
                    "track": "v1",
                    "clipType": "text-card",
                    "hold": 2,
                    "params": {"content": "Hello", "entrance": ["missing"]},
                }
            ],
        }
        with (
            mock.patch.object(timeline, "_animation_ids", return_value={"fade-up"}),
            self.assertRaisesRegex(ValueError, "animations catalog"),
        ):
            timeline.validate_timeline(config)

    def test_effect_params_reject_animation_phase_mismatch(self) -> None:
        config = {
            "theme": "banodoco-default",
            "clips": [
                {
                    "id": "title",
                    "at": 0,
                    "track": "v1",
                    "clipType": "text-card",
                    "hold": 2,
                    "params": {"content": "Hello", "entrance": ["fade"]},
                }
            ],
        }
        with (
            mock.patch.object(timeline, "_animation_ids", return_value={"fade"}),
            mock.patch.object(timeline, "_animation_meta", return_value={"kind": "wrapper", "phase": "exit"}),
            self.assertRaisesRegex(ValueError, "expected 'entrance'"),
        ):
            timeline.validate_timeline(config)

    def test_transition_validation_rejects_unknown_id(self) -> None:
        config = {
            "theme": "banodoco-default",
            "clips": [
                {"id": "a", "at": 0, "track": "v1", "clipType": "media", "hold": 1, "transition": "wipe"},
                {"id": "b", "at": 1, "track": "v1", "clipType": "media", "hold": 1},
            ],
        }
        with (
            mock.patch.object(timeline, "_transition_ids", return_value={"fade"}),
            self.assertRaisesRegex(ValueError, "transitions catalog"),
        ):
            timeline.validate_timeline(config)

    def test_transition_validation_rejects_duration_that_exceeds_adjacent_clip(self) -> None:
        config = {
            "theme": "banodoco-default",
            "clips": [
                {"id": "a", "at": 0, "track": "v1", "clipType": "media", "hold": 1, "transition": {"id": "fade", "durationFrames": 45}},
                {"id": "b", "at": 1, "track": "v1", "clipType": "media", "hold": 1},
            ],
        }
        with (
            mock.patch.object(timeline, "_transition_ids", return_value={"fade"}),
            self.assertRaisesRegex(ValueError, "fit both adjacent"),
        ):
            timeline.validate_timeline(config)

    def test_transition_validation_allows_valid_adjacent_same_track_duration(self) -> None:
        config = {
            "theme": "banodoco-default",
            "clips": [
                {"id": "a", "at": 0, "track": "v1", "clipType": "media", "hold": 1, "transition": {"id": "fade", "durationFrames": 12}},
                {"id": "b", "at": 1, "track": "v1", "clipType": "media", "hold": 1},
                {"id": "overlay", "at": 0.2, "track": "v2", "clipType": "media", "hold": 0.2, "transition": {"id": "fade", "durationFrames": 12}},
            ],
        }
        with mock.patch.object(timeline, "_transition_ids", return_value={"fade"}):
            timeline.validate_timeline(config)


if __name__ == "__main__":
    unittest.main()
