import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from artagents import timeline


class ArrangementSchemaTest(unittest.TestCase):
    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="arrangement-schema-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def fixture_arrangement(self) -> dict:
        return {
            "version": timeline.ARRANGEMENT_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "brief_text": "Open with dialogue and cover with b-roll.",
            "target_duration_sec": 75.0,
            "source_slug": "ados",
            "brief_slug": "hype",
            "pool_sha256": "poolsha",
            "brief_sha256": "briefsha",
            "clips": [
                {
                    "uuid": "a3f4b21c",
                    "order": 1,
                    "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [0.0, 5.0]},
                    "visual_source": {"pool_id": "pool_v_0001", "role": "overlay"},
                    "text_overlay": {"content": "ADOS 2026", "style_preset": "title"},
                    "rationale": "Open on the hook.",
                }
            ],
        }

    def test_roundtrip_is_byte_stable(self) -> None:
        arrangement = self.fixture_arrangement()
        tmp_dir = self.make_tempdir()
        path = tmp_dir / "arrangement.json"

        timeline.save_arrangement(arrangement, path, {"pool_d_0001", "pool_v_0001"})
        loaded = timeline.load_arrangement(path, {"pool_d_0001", "pool_v_0001"})

        self.assertEqual(path.read_text(encoding="utf-8"), json.dumps(arrangement, indent=2) + "\n")
        self.assertEqual(loaded, arrangement)

    def test_load_arrangement_migrates_missing_clip_uuids_and_persists(self) -> None:
        arrangement = self.fixture_arrangement()
        del arrangement["clips"][0]["uuid"]
        tmp_dir = self.make_tempdir()
        path = tmp_dir / "old-arrangement.json"
        path.write_text(json.dumps(arrangement, indent=2) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, r"Arrangement\.clips\[0\]\.uuid is required"):
            timeline.load_arrangement(path, {"pool_d_0001", "pool_v_0001"})

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            loaded = timeline.load_arrangement(
                path,
                {"pool_d_0001", "pool_v_0001"},
                assign_missing_uuids=True,
            )

        migrated_uuid = loaded["clips"][0]["uuid"]
        self.assertRegex(migrated_uuid, r"^[0-9a-f]{8}$")
        self.assertEqual(
            stderr.getvalue().strip(),
            f"timeline.load_arrangement: migrated clip order=1 uuid={migrated_uuid}",
        )
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["clips"][0]["uuid"], migrated_uuid)
        reloaded = timeline.load_arrangement(path, {"pool_d_0001", "pool_v_0001"})
        self.assertEqual(reloaded["clips"][0]["uuid"], migrated_uuid)
        with self.assertRaisesRegex(ValueError, r"Arrangement\.clips\[0\]\.uuid is required"):
            timeline.save_arrangement(arrangement, tmp_dir / "still-strict.json", {"pool_d_0001", "pool_v_0001"})

    def test_validate_arrangement_rejects_unknown_visual_source(self) -> None:
        arrangement = self.fixture_arrangement()
        arrangement["clips"][0]["visual_source"]["pool_id"] = "pool_v_9999"
        with self.assertRaises(ValueError):
            timeline.validate_arrangement(arrangement, {"pool_d_0001", "pool_v_0001"})

    def test_validate_arrangement_rejects_missing_clip_uuid(self) -> None:
        arrangement = self.fixture_arrangement()
        del arrangement["clips"][0]["uuid"]

        with self.assertRaisesRegex(ValueError, r"Arrangement\.clips\[0\]\.uuid is required"):
            timeline.validate_arrangement(arrangement, {"pool_d_0001", "pool_v_0001"})

    def test_validate_arrangement_rejects_non_hex_clip_uuid(self) -> None:
        arrangement = self.fixture_arrangement()
        arrangement["clips"][0]["uuid"] = "not-hex!"

        with self.assertRaisesRegex(ValueError, r"Arrangement\.clips\[0\]\.uuid must be an 8-character lowercase hex string"):
            timeline.validate_arrangement(arrangement, {"pool_d_0001", "pool_v_0001"})

    def test_validate_arrangement_rejects_duplicate_clip_uuid(self) -> None:
        arrangement = self.fixture_arrangement()
        arrangement["clips"].append(
            {
                "uuid": "a3f4b21c",
                "order": 2,
                "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [5.0, 8.0]},
                "visual_source": None,
                "text_overlay": None,
                "rationale": "Continue the quote cleanly.",
            }
        )

        with self.assertRaisesRegex(ValueError, r"Arrangement\.clips\[1\]\.uuid 'a3f4b21c' is not unique"):
            timeline.validate_arrangement(arrangement, {"pool_d_0001", "pool_v_0001"})

    def test_validate_arrangement_rejects_forbidden_time_keys_at_any_depth(self) -> None:
        base = self.fixture_arrangement()
        for key in ("src_start", "src_end", "duration", "from", "to", "at", "start", "end", "time"):
            arrangement = json.loads(json.dumps(base))
            arrangement["clips"][0]["text_overlay"][key] = 1
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    timeline.validate_arrangement(arrangement, {"pool_d_0001", "pool_v_0001"})

    def test_validate_arrangement_rejects_overlapping_trims_on_same_pool_id(self) -> None:
        arrangement = self.fixture_arrangement()
        arrangement["clips"].append(
            {
                "uuid": "b8e7c610",
                "order": 2,
                "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [4.5, 8.0]},
                "visual_source": None,
                "text_overlay": None,
                "rationale": "Continue the quote.",
            }
        )

        with self.assertRaisesRegex(ValueError, "clips 1 and 2 overlap"):
            timeline.validate_arrangement(arrangement, {"pool_d_0001", "pool_v_0001"})

    def test_validate_arrangement_allows_disjoint_trims_on_same_pool_id(self) -> None:
        arrangement = self.fixture_arrangement()
        arrangement["clips"].append(
            {
                "uuid": "b8e7c610",
                "order": 2,
                "audio_source": {"pool_id": "pool_d_0001", "trim_sub_range": [5.0, 8.0]},
                "visual_source": None,
                "text_overlay": None,
                "rationale": "Continue the quote cleanly.",
            }
        )

        timeline.validate_arrangement(arrangement, {"pool_d_0001", "pool_v_0001"})


if __name__ == "__main__":
    unittest.main()
