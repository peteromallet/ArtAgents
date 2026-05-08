import json
import shutil
import tempfile
import unittest
from pathlib import Path

from astrid import timeline


ROOT = Path(__file__).resolve().parents[1]


def _synthetic_scenes() -> list[dict]:
    # The original test loaded runs/ados_loose/scenes.json, which is a per-user
    # render output that has never been tracked in git. The pool-schema tests
    # only need scenes[0] to supply start/end/duration/index — they do not
    # depend on the real ados_loose values — so we generate a synthetic scene
    # with the same shape.
    return [
        {"index": 0, "start": 0.0, "end": 5.4, "duration": 5.4},
    ]


def _synthetic_transcript() -> list[dict]:
    # Same rationale as _synthetic_scenes: the test indexes segments 185 and
    # 186 only to grab consistent timestamps. We pre-populate the indices used
    # by the fixture (185, 186) with monotonically increasing timestamps.
    segments = [{"start": float(i), "end": float(i) + 0.5} for i in range(187)]
    segments[185] = {"start": 185.0, "end": 185.6}
    segments[186] = {"start": 185.6, "end": 186.4}
    return segments


class PoolSchemaTest(unittest.TestCase):
    maxDiff = None

    def make_tempdir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="pool-schema-"))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def fixture_pool(self) -> tuple[dict, list[dict], list[dict]]:
        scenes = _synthetic_scenes()
        transcript = _synthetic_transcript()
        scene = scenes[0]
        pool = {
            "version": timeline.POOL_VERSION,
            "generated_at": "2026-04-21T12:00:00Z",
            "source_slug": "ados_loose",
            "entries": [
                {
                    "id": "pool_d_0001",
                    "kind": "source",
                    "category": "dialogue",
                    "asset": "main",
                    "src_start": transcript[185]["start"],
                    "src_end": transcript[186]["end"],
                    "duration": transcript[186]["end"] - transcript[185]["start"],
                    "source_ids": {"segment_ids": [185, 186]},
                    "scores": {"quotability": 0.8},
                    "excluded": False,
                    "text": "Round of applause for Kajai.",
                    "speaker": None,
                    "quote_kind": "crowd",
                },
                {
                    "id": "pool_v_0001",
                    "kind": "source",
                    "category": "visual",
                    "asset": "main",
                    "src_start": scene["start"],
                    "src_end": scene["end"],
                    "duration": scene["duration"],
                    "source_ids": {"scene_id": f"scene_{int(scene['index']):03d}"},
                    "scores": {"triage": 0.8, "deep": 0.7},
                    "excluded": False,
                    "motion_tags": ["speaker"],
                    "mood_tags": ["stage"],
                    "subject": "opening scene",
                    "camera": "wide",
                },
                {
                    "id": "pool_r_0001",
                    "kind": "source",
                    "category": "reaction",
                    "asset": "main",
                    "src_start": transcript[186]["start"],
                    "src_end": transcript[186]["end"],
                    "duration": transcript[186]["end"] - transcript[186]["start"],
                    "source_ids": {"segment_ids": [186]},
                    "scores": {},
                    "excluded": False,
                    "intensity": 1.0,
                    "event_label": "laughter",
                },
                {
                    "id": "pool_a_0001",
                    "kind": "source",
                    "category": "applause",
                    "asset": "main",
                    "src_start": transcript[185]["start"],
                    "src_end": transcript[185]["end"],
                    "duration": transcript[185]["end"] - transcript[185]["start"],
                    "source_ids": {"segment_ids": [185]},
                    "scores": {},
                    "excluded": False,
                    "intensity": 1.0,
                    "event_label": "applause",
                },
                {
                    "id": "pool_m_0001",
                    "kind": "source",
                    "category": "music",
                    "asset": "main",
                    "src_start": 0.0,
                    "src_end": 3.0,
                    "duration": 3.0,
                    "source_ids": {},
                    "scores": {},
                    "excluded": False,
                    "bed_kind": "pulse",
                    "energy": 0.5,
                },
            ],
        }
        return pool, scenes, transcript

    def test_roundtrip_and_fixture_ranges(self) -> None:
        pool, scenes, transcript = self.fixture_pool()
        tmp_dir = self.make_tempdir()
        path = tmp_dir / "pool.json"

        timeline.save_pool(pool, path)
        loaded = timeline.load_pool(path)

        self.assertEqual(path.read_text(encoding="utf-8"), json.dumps(pool, indent=2) + "\n")
        self.assertEqual(loaded, pool)
        visual = next(entry for entry in loaded["entries"] if entry["category"] == "visual")
        dialogue = next(entry for entry in loaded["entries"] if entry["category"] == "dialogue")
        self.assertEqual(visual["src_start"], scenes[0]["start"])
        self.assertEqual(visual["src_end"], scenes[0]["end"])
        self.assertEqual(dialogue["src_start"], transcript[185]["start"])
        self.assertEqual(dialogue["src_end"], transcript[186]["end"])

    def test_validate_pool_rejects_negative_duration(self) -> None:
        pool, _, _ = self.fixture_pool()
        pool["entries"][0]["duration"] = -1.0
        with self.assertRaises(ValueError):
            timeline.validate_pool(pool)

    def test_validate_pool_rejects_missing_id(self) -> None:
        pool, _, _ = self.fixture_pool()
        del pool["entries"][0]["id"]
        with self.assertRaises(ValueError):
            timeline.validate_pool(pool)

    def test_validate_pool_rejects_unknown_kind(self) -> None:
        pool, _, _ = self.fixture_pool()
        pool["entries"][0]["kind"] = "ghost"
        with self.assertRaises(ValueError):
            timeline.validate_pool(pool)

    def test_validate_pool_accepts_generative_entry(self) -> None:
        pool, _, _ = self.fixture_pool()
        pool["entries"].append(
            {
                "id": "pool_g_text_card",
                "kind": "generative",
                "category": "visual",
                "effect_id": "text-card",
                "param_schema": {"type": "object"},
                "defaults": {"align": "center"},
                "meta": {"id": "text-card", "name": "Text Card"},
                "duration": None,
                "scores": {},
                "excluded": False,
            }
        )
        timeline.validate_pool(pool)


if __name__ == "__main__":
    unittest.main()
