from pathlib import Path
import unittest

from artagents import enriched_arrangement
from reviewers.overlay_fit import OverlayFitReviewer
from reviewers.speaker_flow import SpeakerFlowReviewer
from reviewers.visual_quality import VisualQualityReviewer


def make_clip(
    order: int,
    *,
    audio_source=None,
    visual_source=None,
    pool_entry=None,
    audio_pool_entry=None,
    visual_pool_entry=None,
    primary=None,
    overlay=None,
    zones=None,
) -> enriched_arrangement.EnrichedClip:
    return enriched_arrangement.EnrichedClip(
        order=order,
        asset_key="main",
        clip={
            "uuid": f"{order:08x}",
            "order": order,
            "audio_source": audio_source,
            "visual_source": visual_source,
        },
        pool_entry=pool_entry,
        audio_pool_entry=audio_pool_entry,
        visual_pool_entry=visual_pool_entry,
        timeline_clips={},
        audio_timeline_clip=None,
        primary_visual_timeline_clip=primary,
        overlay_timeline_clip=overlay,
        text_timeline_clip=None,
        transcript_segments=[],
        scenes=[],
        zones=zones or [],
    )


def make_enriched(*clips: enriched_arrangement.EnrichedClip) -> enriched_arrangement.EnrichedArrangement:
    return enriched_arrangement.EnrichedArrangement(
        run_dir=Path("."),
        arrangement={},
        arrangement_path=Path("arrangement.json"),
        timeline=None,
        timeline_path=Path("hype.timeline.json"),
        metadata={},
        metadata_path=Path("hype.metadata.json"),
        pool={},
        pool_path=Path("pool.json"),
        pool_by_id={},
        clips=list(clips),
        clips_by_order={clip.order: clip for clip in clips},
        transcript_by_asset={"main": []},
        scenes_by_asset={"main": []},
        zones_by_asset={"main": []},
    )


class ReviewerModulesTest(unittest.TestCase):
    def test_visual_quality_flags_overlap_and_ignores_missing_zones(self) -> None:
        with_zones = make_clip(
            1,
            primary={"from_": 0.0, "to": 4.0},
            zones=[enriched_arrangement.QualityZone(kind=enriched_arrangement.ZoneKind.VIDEO_DEAD, start=0.0, end=1.0)],
        )
        without_zones = make_clip(2, primary={"from_": 0.0, "to": 4.0}, zones=[])
        findings = VisualQualityReviewer().review(make_enriched(with_zones, without_zones))
        self.assertEqual([finding.code for finding in findings], ["visual_dead_overlap"])
        self.assertEqual([finding.clip_uuid for finding in findings], ["00000001"])

    def test_speaker_flow_flags_repeat_and_ignores_none(self) -> None:
        repeat_a = make_clip(
            1,
            audio_source={"pool_id": "a", "trim_sub_range": [0.0, 5.0]},
            pool_entry={"speaker": "A"},
            audio_pool_entry={"kind": "source",
                    "category": "dialogue"},
        )
        repeat_b = make_clip(
            2,
            audio_source={"pool_id": "b", "trim_sub_range": [7.0, 12.0]},
            pool_entry={"speaker": "A"},
            audio_pool_entry={"kind": "source",
                    "category": "dialogue"},
        )
        none_speaker = make_clip(
            3,
            audio_source={"pool_id": "c", "trim_sub_range": [12.0, 16.0]},
            pool_entry={"speaker": None},
            audio_pool_entry={"kind": "source",
                    "category": "dialogue"},
        )
        findings = SpeakerFlowReviewer().review(make_enriched(repeat_a, repeat_b))
        self.assertEqual([finding.code for finding in findings], ["speaker_repeat_without_break"])
        self.assertEqual([finding.clip_uuid for finding in findings], ["00000002"])
        self.assertEqual(SpeakerFlowReviewer().review(make_enriched(repeat_b, none_speaker)), [])

    def test_overlay_fit_flags_insufficient_coverage(self) -> None:
        overlay_clip = make_clip(
            1,
            audio_source={"pool_id": "d", "trim_sub_range": [0.0, 5.0]},
            visual_source={"pool_id": "ov", "role": "overlay"},
            visual_pool_entry={"src_start": 0.0, "src_end": 2.0},
        )
        findings = OverlayFitReviewer().review(make_enriched(overlay_clip))
        self.assertEqual([finding.code for finding in findings], ["overlay_insufficient_coverage"])
        self.assertEqual([finding.clip_uuid for finding in findings], ["00000001"])


if __name__ == "__main__":
    unittest.main()
