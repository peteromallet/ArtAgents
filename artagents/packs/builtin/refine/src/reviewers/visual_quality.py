from __future__ import annotations

from artagents.domains.hype import enriched_arrangement
from artagents.packs.builtin.refine.src.reviewers import Reviewer


class VisualQualityReviewer(Reviewer):
    name = "visual_quality"

    def review(self, enriched: enriched_arrangement.EnrichedArrangement) -> list[enriched_arrangement.ReviewerFinding]:
        findings: list[enriched_arrangement.ReviewerFinding] = []
        for clip in enriched.clips:
            timeline_clip = clip.overlay_timeline_clip or clip.primary_visual_timeline_clip
            if not timeline_clip:
                continue
            clip_start = float(timeline_clip.get("from_", timeline_clip.get("from", 0.0)))
            clip_end = float(timeline_clip.get("to", clip_start))
            duration = max(0.0, clip_end - clip_start)
            if duration <= 0:
                continue
            overlap = sum(
                max(0.0, min(clip_end, zone.end) - max(clip_start, zone.start))
                for zone in clip.zones
                if zone.kind is enriched_arrangement.ZoneKind.VIDEO_DEAD
            )
            threshold = max(0.5, duration * 0.15)
            if overlap < threshold:
                continue
            findings.append(
                enriched_arrangement.ReviewerFinding(
                    clip_order=clip.order,
                    clip_uuid=clip.uuid,
                    code="visual_dead_overlap",
                    severity=enriched_arrangement.FindingSeverity.FLAG,
                    message=f"Visual source overlaps video-dead zones for {overlap:.2f}s ({threshold:.2f}s threshold)",
                    reviewer=self.name,
                )
            )
        return findings
