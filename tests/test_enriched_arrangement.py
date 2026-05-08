import json
from pathlib import Path
import unittest

from astrid.domains.hype import enriched_arrangement

from tests.helpers.fixture_case import make_brief_case


def make_clip(
    *,
    trim_sub_range=None,
    transcript_segments=None,
    audio_pool_entry=None,
) -> enriched_arrangement.EnrichedClip:
    return enriched_arrangement.EnrichedClip(
        order=1,
        asset_key="main",
        clip={"order": 1, "uuid": "00000001", "audio_source": {"trim_sub_range": trim_sub_range}},
        pool_entry=None,
        audio_pool_entry=audio_pool_entry,
        visual_pool_entry=None,
        timeline_clips={},
        audio_timeline_clip=None,
        primary_visual_timeline_clip=None,
        overlay_timeline_clip=None,
        text_timeline_clip=None,
        transcript_segments=transcript_segments or [],
        scenes=[],
        zones=[],
    )


class EnrichedArrangementTest(unittest.TestCase):
    def test_expected_text_for_clip_uses_overlapping_transcript_segments(self) -> None:
        clip = make_clip(
            trim_sub_range=[1.0, 3.0],
            transcript_segments=[
                {"start": 0.0, "end": 1.0, "text": "outside before"},
                {"start": 1.0, "end": 2.0, "text": "  First line  "},
                {"start": 2.0, "end": 3.0, "text": "second line  "},
                {"start": 3.0, "end": 4.0, "text": "outside after"},
            ],
            audio_pool_entry={"text": "pool fallback"},
        )

        self.assertEqual(enriched_arrangement.expected_text_for_clip(clip), "First line second line")

    def test_expected_text_for_clip_falls_back_to_pool_text(self) -> None:
        clip = make_clip(
            trim_sub_range=[10.0, 12.0],
            transcript_segments=[{"start": 1.0, "end": 2.0, "text": "not in range"}],
            audio_pool_entry={"text": "  Pool fallback text  "},
        )

        self.assertEqual(enriched_arrangement.expected_text_for_clip(clip), "Pool fallback text")

    def test_expected_text_for_clip_returns_empty_when_no_sources_have_text(self) -> None:
        clip = make_clip(trim_sub_range=[10.0, 12.0])

        self.assertEqual(enriched_arrangement.expected_text_for_clip(clip), "")

    def test_load_resolves_pool_entries_timeline_and_zones(self) -> None:
        case = make_brief_case(self)
        enriched = enriched_arrangement.load(Path(case["run_dir"]))

        self.assertEqual([clip.order for clip in enriched.clips[:3]], [1, 2, 3])
        self.assertEqual(enriched.clips_by_order[2].uuid, "00000002")
        self.assertEqual(enriched.clips_by_order[2].pool_entry["speaker"], "Host A")
        self.assertEqual(enriched.clips_by_order[2].audio_timeline_clip["id"], "clip_a_2")
        self.assertEqual(enriched.clips_by_order[2].primary_visual_timeline_clip["id"], "clip_v1_2")
        self.assertEqual(enriched.clips_by_order[1].overlay_timeline_clip["id"], "clip_v2_1")
        self.assertEqual([zone.kind.value for zone in enriched.zones_by_asset["main"]], ["video_dead", "audio_dead"])

    def test_load_treats_missing_quality_zone_ref_as_empty(self) -> None:
        case = make_brief_case(self)
        metadata_path = Path(case["metadata_path"])
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        del payload["sources"]["main"]["quality_zones_ref"]
        metadata_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        enriched = enriched_arrangement.load(Path(case["run_dir"]))
        self.assertEqual(enriched.zones_by_asset["main"], [])

    def test_load_migrates_old_arrangement_missing_uuids(self) -> None:
        case = make_brief_case(self)
        arrangement_path = Path(case["arrangement_path"])
        payload = json.loads(arrangement_path.read_text(encoding="utf-8"))
        for clip in payload["clips"]:
            clip.pop("uuid", None)
        arrangement_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        enriched = enriched_arrangement.load(Path(case["run_dir"]))

        migrated = [clip.uuid for clip in enriched.clips]
        self.assertEqual(len(migrated), len(set(migrated)))
        for clip_uuid in migrated:
            self.assertRegex(clip_uuid, r"^[0-9a-f]{8}$")


if __name__ == "__main__":
    unittest.main()
