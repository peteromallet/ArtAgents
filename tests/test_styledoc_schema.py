import json
import shutil
import tempfile
import unittest
from pathlib import Path

from artagents import theme_schema
from artagents.theme_schema import ThemeValidationError, load_theme, resolve_theme_asset


ROOT = Path(__file__).resolve().parents[2]
ARCA_THEME = ROOT / "themes" / "arca-gidan" / "theme.json"


def base_theme() -> dict:
    return {
        "id": "fixture",
        "visual": {
            "color": {"fg": "#fff", "bg": "#000", "accent": "#f00"},
            "type": {
                "families": {"heading": "serif", "body": "serif"},
                "size": {"base": 64, "small": 36, "large": 96},
                "weight": {"normal": 400, "bold": 700},
                "lineHeight": 1.1,
            },
            "motion": {"fadeMs": 200},
            "canvas": {"width": 1920, "height": 1080, "fps": 30},
        },
    }


class StyledocSchemaTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="styledoc-schema-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def write_theme(self, payload: dict) -> Path:
        path = self.make_tempdir() / "theme.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_arca_gidan_theme_has_five_blocks_and_object_assets(self) -> None:
        if not ARCA_THEME.is_file():
            self.skipTest("themes/arca-gidan/theme.json is authored by T11")
        theme = load_theme(ARCA_THEME)

        self.assertEqual(
            set(theme),
            {"id", "visual", "generation", "voice", "audio", "pacing"},
        )
        reference = theme["generation"]["references"][0]
        asset = theme["generation"]["assets"][0]
        self.assertIsInstance(reference, dict)
        self.assertIsInstance(asset, dict)
        self.assertIn("file", reference)
        self.assertIn("description", reference)
        self.assertIn("file", asset)
        self.assertIn("description", asset)

    def test_rejects_bare_string_references_with_specific_message(self) -> None:
        payload = base_theme()
        payload["generation"] = {"references": ["foo.jpg"]}
        with self.assertRaises(ThemeValidationError) as exc_info:
            load_theme(self.write_theme(payload))

        message = str(exc_info.exception)
        self.assertIn("references[0]", message)
        self.assertIn("'file'", message)
        self.assertIn("'description'", message)

    def test_missing_visual_is_rejected(self) -> None:
        payload = base_theme()
        payload.pop("visual")
        with self.assertRaises(ThemeValidationError):
            load_theme(self.write_theme(payload))

    def test_missing_voice_loads(self) -> None:
        payload = base_theme()
        loaded = load_theme(self.write_theme(payload))
        self.assertEqual(loaded["id"], "fixture")
        self.assertNotIn("voice", loaded)

    def test_resolve_theme_asset_rejects_path_escape(self) -> None:
        theme_dir = self.make_tempdir()
        with self.assertRaises(ThemeValidationError):
            resolve_theme_asset(theme_dir, "../etc/passwd")

    def test_hand_rolled_references_check_is_independent_of_jsonschema(self) -> None:
        payload = base_theme()
        payload["generation"] = {"references": ["foo.jpg"]}
        with self.assertRaises(ThemeValidationError) as exc_info:
            theme_schema._check_generation_file_items(payload)

        self.assertIn("references[0]", str(exc_info.exception))


if __name__ == "__main__":
    unittest.main()
