from __future__ import annotations

from artagents.domains.hype import enriched_arrangement
from artagents.packs.builtin.refine.src.reviewers import Reviewer


class SpeakerFlowReviewer(Reviewer):
    name = "speaker_flow"

    def review(self, enriched: enriched_arrangement.EnrichedArrangement) -> list[enriched_arrangement.ReviewerFinding]:
        dialogue_clips = [clip for clip in enriched.clips if clip.audio_pool_entry and clip.audio_pool_entry.get("category") == "dialogue"]
        findings: list[enriched_arrangement.ReviewerFinding] = []
        for first, second in zip(dialogue_clips, dialogue_clips[1:]):
            speaker_a = first.pool_entry.get("speaker") if first.pool_entry else None
            speaker_b = second.pool_entry.get("speaker") if second.pool_entry else None
            if speaker_a is None or speaker_b is None or speaker_a != speaker_b:
                continue
            if _has_intervening_stinger(enriched, first.order, second.order):
                continue
            if _trim_contiguous(first, second):
                continue
            findings.append(
                enriched_arrangement.ReviewerFinding(
                    clip_order=second.order,
                    clip_uuid=second.uuid,
                    code="speaker_repeat_without_break",
                    severity=enriched_arrangement.FindingSeverity.FLAG,
                    message=f"Adjacent dialogue clips repeat speaker {speaker_a!r} without a stinger break",
                    reviewer=self.name,
                )
            )
        return findings


def _has_intervening_stinger(
    enriched: enriched_arrangement.EnrichedArrangement, first_order: int, second_order: int
) -> bool:
    return any(
        clip.order > first_order
        and clip.order < second_order
        and isinstance(clip.clip.get("visual_source"), dict)
        and clip.clip["visual_source"].get("role") == "stinger"
        for clip in enriched.clips
    )


def _trim_contiguous(
    first: enriched_arrangement.EnrichedClip, second: enriched_arrangement.EnrichedClip
) -> bool:
    first_audio = first.clip.get("audio_source") or {}
    second_audio = second.clip.get("audio_source") or {}
    if first_audio.get("pool_id") != second_audio.get("pool_id"):
        return False
    first_trim = first_audio.get("trim_sub_range") or []
    second_trim = second_audio.get("trim_sub_range") or []
    if len(first_trim) != 2 or len(second_trim) != 2:
        return False
    return abs(float(first_trim[1]) - float(second_trim[0])) <= 1e-6
