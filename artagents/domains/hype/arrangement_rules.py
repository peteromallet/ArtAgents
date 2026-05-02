"""Shared arrangement validation and compilation rules for hype-cut assembly."""

from __future__ import annotations

from typing import Any

ROLE_DURATION_BOUNDS = {"primary": (4.0, 10.0), "overlay": (4.0, 10.0), "stinger": (2.0, 8.0)}
TOTAL_DURATION_BOUNDS = (70.0, 95.0)
TRIM_BOUND_EXTENSION_SEC = 0.6
MIN_OVERLAY_COVERAGE_SEC = 4.0
MAX_VISUAL_HOLD_RATIO = 0.2

__all__ = [
    "ROLE_DURATION_BOUNDS",
    "TOTAL_DURATION_BOUNDS",
    "TRIM_BOUND_EXTENSION_SEC",
    "MIN_OVERLAY_COVERAGE_SEC",
    "MAX_VISUAL_HOLD_RATIO",
    "compile_arrangement_plan",
]

_ROLE_TRACK_MAP = {"primary": "v1", "overlay": "v2", "stinger": "v2"}


def _pool_map(pool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["id"]: entry for entry in pool.get("entries", [])}


def _source_duration(entry: dict[str, Any]) -> float:
    if entry.get("kind") == "generative":
        return 0.0
    return max(0.0, float(entry["src_end"]) - float(entry["src_start"]))


def _trim_sub_range(audio_source: dict[str, Any], *, order: int) -> tuple[float, float]:
    trim_sub_range = audio_source["trim_sub_range"]
    trim_start = float(trim_sub_range[0])
    trim_end = float(trim_sub_range[1])
    if trim_end <= trim_start:
        raise ValueError(f"Arrangement clip {order} has a non-positive trim_sub_range")
    return trim_start, trim_end


def _plan_label(plan: dict[str, Any]) -> str:
    overlay_entry = plan.get("overlay_entry")
    overlay_label = overlay_entry["id"] if isinstance(overlay_entry, dict) else "none"
    return (
        f"order={plan['order']} "
        f"duration={plan['duration']:.2f}s "
        f"role={plan['role']} "
        f"audio={plan['audio_entry']['id'] if plan['audio_entry'] is not None else 'none'} "
        f"overlay={overlay_label}"
    )


def _raise_total_duration_error(plans: list[dict[str, Any]], total_duration: float) -> None:
    min_total, max_total = TOTAL_DURATION_BOUNDS
    if min_total <= total_duration <= max_total:
        return
    direction = "undershoots" if total_duration < min_total else "overshoots"
    bound = min_total if total_duration < min_total else max_total
    delta = abs(total_duration - bound)
    longest = ", ".join(_plan_label(plan) for plan in sorted(plans, key=lambda item: item["duration"], reverse=True)[:3])
    raise ValueError(
        f"Arrangement total duration {total_duration:.2f}s {direction} the allowed "
        f"{min_total:.0f}-{max_total:.0f}s window by {delta:.2f}s. Longest clips: {longest}"
    )


def compile_arrangement_plan(arrangement: dict[str, Any], pool: dict[str, Any]) -> list[dict[str, Any]]:
    pool_entries = _pool_map(pool)
    generative_only = all(
        isinstance(clip.get("visual_source"), dict)
        and pool_entries[clip["visual_source"]["pool_id"]].get("kind") == "generative"
        and clip.get("audio_source") is None
        for clip in arrangement["clips"]
    )
    generative_slot_duration = (
        float(arrangement["target_duration_sec"]) / len(arrangement["clips"])
        if generative_only and arrangement["clips"]
        else None
    )
    planned: list[dict[str, Any]] = []
    cumulative = 0.0
    for clip_cfg in sorted(arrangement["clips"], key=lambda clip: int(clip["order"])):
        order = int(clip_cfg["order"])
        visual_source = clip_cfg.get("visual_source")
        audio_source = clip_cfg.get("audio_source")

        audio_entry = None
        audio_trim_start: float | None = None
        audio_trim_end: float | None = None
        if isinstance(audio_source, dict):
            audio_entry = pool_entries[audio_source["pool_id"]]
            if audio_entry.get("category") != "dialogue":
                raise ValueError(
                    f"Arrangement clip {order} audio_source.pool_id={audio_source['pool_id']!r} "
                    f"must reference a dialogue pool entry, not {audio_entry.get('category')!r}"
                )
            audio_trim_start, audio_trim_end = _trim_sub_range(audio_source, order=order)
            entry_start = float(audio_entry["src_start"])
            entry_end = float(audio_entry["src_end"])
            lower = entry_start - TRIM_BOUND_EXTENSION_SEC
            upper = entry_end + TRIM_BOUND_EXTENSION_SEC
            if audio_trim_start < lower or audio_trim_end > upper:
                raise ValueError(
                    f"Arrangement clip {order} trim_sub_range "
                    f"[{audio_trim_start:.3f}, {audio_trim_end:.3f}] falls outside "
                    f"audio pool entry {audio_entry['id']} [{entry_start:.3f}, {entry_end:.3f}]"
                )
            audio_trim_start = max(audio_trim_start, lower, 0.0)
            audio_trim_end = min(audio_trim_end, upper)

        overlay_entry = None
        if visual_source is None:
            if audio_entry is None:
                raise ValueError(
                    f"Arrangement clip {order} omits visual_source but has no audio_source; "
                    f"stingers must declare a visual"
                )
            role = "primary"
        else:
            overlay_entry = pool_entries[visual_source["pool_id"]]
            if overlay_entry.get("kind") == "generative":
                role = visual_source["role"]
                if role not in _ROLE_TRACK_MAP:
                    raise ValueError(f"Arrangement clip {order} has unsupported visual role {role!r}")
            elif overlay_entry.get("category") != "visual":
                raise ValueError(
                    f"Arrangement clip {order} visual_source.pool_id={visual_source['pool_id']!r} "
                    f"must reference a visual pool entry, not {overlay_entry.get('category')!r}"
                )
            else:
                role = visual_source["role"]
                if role not in _ROLE_TRACK_MAP:
                    raise ValueError(f"Arrangement clip {order} has unsupported visual role {role!r}")
            if overlay_entry.get("kind") != "generative" and role == "primary":
                raise ValueError(
                    f"Arrangement clip {order} has visual_source with role=primary; "
                    f"primary visuals are derived from audio_source — leave visual_source null"
                )
            if overlay_entry.get("kind") != "generative" and role == "overlay" and audio_entry is None:
                raise ValueError(f"Arrangement clip {order} role=overlay requires audio_source")
            if overlay_entry.get("kind") != "generative" and role == "stinger" and audio_entry is not None:
                raise ValueError(f"Arrangement clip {order} role=stinger must have audio_source=null")

        if audio_entry is not None:
            duration = audio_trim_end - audio_trim_start
        elif overlay_entry is not None and overlay_entry.get("kind") == "generative":
            duration = float(generative_slot_duration or arrangement["target_duration_sec"])
        else:
            duration = _source_duration(overlay_entry)

        min_duration, max_duration = ROLE_DURATION_BOUNDS[role]
        if overlay_entry is not None and overlay_entry.get("kind") == "generative":
            min_duration, max_duration = 0.1, float("inf")
        if duration < min_duration or duration > max_duration:
            raise ValueError(
                f"Arrangement clip {order} has duration {duration:.2f}s for role {role!r}; "
                f"expected {min_duration:.1f}-{max_duration:.1f}s"
            )

        overlay_play_duration: float | None = None
        if overlay_entry is not None and overlay_entry.get("kind") != "generative":
            overlay_source_duration = _source_duration(overlay_entry)
            if role == "stinger":
                # Stingers own the full timeline slot; enforce no-freeze here.
                overlay_hold = max(0.0, duration - overlay_source_duration)
                overlay_hold_ratio = overlay_hold / duration if duration > 0 else 0.0
                if overlay_hold_ratio >= MAX_VISUAL_HOLD_RATIO:
                    raise ValueError(
                        f"Arrangement clip {order} would freeze visual {overlay_entry['id']} for "
                        f"{overlay_hold_ratio:.1%} of its runtime ({duration:.2f}s requested, "
                        f"{overlay_source_duration:.2f}s available)"
                    )
                overlay_play_duration = duration
            else:
                overlay_play_duration = min(duration, overlay_source_duration)
                required_overlay_duration = min(duration * 0.5, MIN_OVERLAY_COVERAGE_SEC)
                if overlay_play_duration < required_overlay_duration:
                    raise ValueError(
                        f"Arrangement clip {order} overlay {overlay_entry['id']!r} only covers "
                        f"{overlay_play_duration:.2f}s of {duration:.2f}s audio; "
                        f"required minimum is {required_overlay_duration:.2f}s"
                    )

        planned.append(
            {
                "order": order,
                "uuid": str(clip_cfg["uuid"]),
                "at": cumulative,
                "duration": duration,
                "audio_entry": audio_entry,
                "audio_trim_start": audio_trim_start,
                "overlay_entry": overlay_entry,
                "overlay_play_duration": overlay_play_duration,
                "visual_params": visual_source.get("params") if isinstance(visual_source, dict) else None,
                "role": role,
                "text_overlay": clip_cfg.get("text_overlay"),
                "rationale": clip_cfg.get("rationale"),
            }
        )
        cumulative += duration
    if not generative_only:
        _raise_total_duration_error(planned, cumulative)
    return planned
