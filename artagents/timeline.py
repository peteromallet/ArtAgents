#!/usr/bin/env python3
"""Timeline schema mirroring reigh-app's TimelineConfig.

TimelineConfig / TimelineClip / ThemeOverrides / TimelineOutput / AssetEntry /
Theme are re-exported from `banodoco_timeline_schema` (see
`packages/timeline-schema/`); the JSON-Schema validator there is the canonical
shape check. Everything else in this file (pool/arrangement/metadata/registry
types, transition validation, effect-id registry checks) is Banodoco-only.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, List, Literal, TypedDict, Union

try:
    from banodoco_timeline_schema import (
        AssetEntry as SharedAssetEntry,
        Theme as SharedTheme,
        ThemeOverrides as SharedThemeOverrides,
        TimelineClip as SharedTimelineClip,
        TimelineConfig as SharedTimelineConfig,
        TimelineOutput as SharedTimelineOutput,
        materialize_output as _materialize_output,
    )
    from banodoco_timeline_schema import validate_timeline as _shared_validate_timeline
except ImportError:
    class SharedTimelineOutput(TypedDict, total=False):
        resolution: str
        fps: float
        file: str
        background: str
        background_scale: float

    class SharedTimelineClip(TypedDict, total=False):
        id: str
        at: float
        track: str
        clipType: str
        asset: str
        from_: float
        to: float
        speed: float
        hold: float
        volume: float
        x: float
        y: float
        width: float
        height: float
        cropTop: float
        cropBottom: float
        cropLeft: float
        cropRight: float
        opacity: float
        params: dict[str, Any]
        text: "TextClipData"
        entrance: "AnimationReferenceList"
        exit: "AnimationReferenceList"
        continuous: "AnimationReferenceList"
        transition: "ClipTransitionReference"
        effects: list["TimelineEffect"]
        source_uuid: str
        generation: dict[str, Any]
        pool_id: str
        clip_order: int

    class SharedThemeOverrides(TypedDict, total=False):
        visual: dict[str, Any]
        generation: dict[str, Any]
        voice: dict[str, Any]
        audio: dict[str, Any]
        pacing: dict[str, Any]

    class SharedTheme(TypedDict, total=False):
        visual: dict[str, Any]
        generation: dict[str, Any]
        voice: dict[str, Any]
        audio: dict[str, Any]
        pacing: dict[str, Any]

    class SharedTimelineConfig(TypedDict, total=False):
        theme: str
        theme_overrides: SharedThemeOverrides
        generation_defaults: dict[str, Any]
        clips: list[SharedTimelineClip]
        tracks: list[dict[str, Any]]
        pinnedShotGroups: list[dict[str, Any]]
        output: SharedTimelineOutput

    class SharedAssetEntry(TypedDict, total=False):
        file: str
        url: str
        etag: str
        content_sha256: str
        url_expires_at: str
        type: str
        duration: float
        resolution: str
        fps: float
        generationId: str

    def _materialize_output(config: SharedTimelineConfig, theme: dict[str, Any]) -> SharedTimelineOutput:
        canvas = theme.get("visual", {}).get("canvas", {}) if isinstance(theme, dict) else {}
        width = int(canvas.get("width", 1920)) if isinstance(canvas, dict) else 1920
        height = int(canvas.get("height", 1080)) if isinstance(canvas, dict) else 1080
        fps = float(canvas.get("fps", 30)) if isinstance(canvas, dict) else 30.0
        return {"resolution": f"{width}x{height}", "fps": fps, "file": "output.mp4"}

    def _shared_validate_timeline(config: Any, *, strict: bool = True) -> None:
        if not isinstance(config, dict):
            raise ValueError("Timeline must be a JSON object")
        if not isinstance(config.get("clips"), list):
            raise ValueError("Timeline.clips must be a list")

TimelineClip = SharedTimelineClip
TimelineConfig = SharedTimelineConfig
ThemeOverrides = SharedThemeOverrides
TimelineOutput = SharedTimelineOutput
AssetEntry = SharedAssetEntry
Theme = SharedTheme

materialize_output = _materialize_output

ParameterType = Literal["number", "select", "boolean", "color", "audio-binding"]
TrackKind = Literal["visual", "audio"]
TrackFit = Literal["cover", "contain", "manual"]
TrackBlendMode = Literal[
    "normal", "multiply", "screen", "overlay",
    "darken", "lighten", "soft-light", "hard-light",
]
BUILTIN_CLIP_TYPES = ("media", "hold", "text", "effect-layer")
ClipType = str
TextAlignment = Literal["left", "center", "right"]
AudioBindingSource = Literal["bass", "mid", "treble", "amplitude"]

class TimelineEffect(TypedDict, total=False):
    fade_in: float
    fade_out: float

class AnimationReferenceObject(TypedDict, total=False):
    id: str
    durationFrames: float
    easing: str
    params: dict[str, Any]

AnimationReference = Union[str, AnimationReferenceObject]
AnimationReferenceList = Union[AnimationReference, List[AnimationReference]]

class AudioBindingValue(TypedDict):
    source: AudioBindingSource
    min: float
    max: float

class ParameterOption(TypedDict):
    label: str
    value: str

class _ParameterDefinitionRequired(TypedDict):
    name: str
    label: str
    description: str
    type: ParameterType

class ParameterDefinition(_ParameterDefinitionRequired, total=False):
    default: Any
    min: float
    max: float
    step: float
    options: list[ParameterOption]

class _TrackDefinitionRequired(TypedDict):
    id: str
    kind: TrackKind
    label: str

class TrackDefinition(_TrackDefinitionRequired, total=False):
    scale: float
    fit: TrackFit
    opacity: float
    volume: float
    muted: bool
    blendMode: TrackBlendMode

class ClipEntrance(TypedDict, total=False):
    type: str
    duration: float
    intensity: float
    params: dict[str, Any]

class ClipExit(TypedDict, total=False):
    type: str
    duration: float
    intensity: float
    params: dict[str, Any]

class ClipContinuous(TypedDict, total=False):
    type: str
    intensity: float
    params: dict[str, Any]

class ClipTransition(TypedDict):
    type: str
    duration: float

class ClipTransitionReference(TypedDict, total=False):
    id: str
    type: str
    duration: float
    durationFrames: float
    params: dict[str, Any]

class TextClipData(TypedDict, total=False):
    content: str
    fontFamily: str
    fontSize: float
    color: str
    align: TextAlignment
    bold: bool
    italic: bool

# TimelineClip / TimelineConfig / ThemeOverrides / TimelineOutput / AssetEntry
# come from banodoco_timeline_schema (re-exported above). PinnedShotGroup and
# AssetRegistry are Banodoco-only wrappers retained here.

AssetRegistryEntry = AssetEntry

class AssetRegistry(TypedDict):
    assets: dict[str, AssetRegistryEntry]

PoolKind = Literal["source", "generative"]
PoolCategory = Literal["dialogue", "visual", "reaction", "applause", "music"]
PipelinePoolKind = Literal["dialogue", "visual", "reaction", "applause", "music", "text"]

class SourceIds(TypedDict, total=False):
    segment_ids: list[int]
    scene_id: str

class PoolScores(TypedDict, total=False):
    triage: float
    deep: float
    quotability: float

class _PoolEntryRequired(TypedDict):
    id: str
    kind: PoolKind
    category: PoolCategory
    duration: float
    scores: PoolScores
    excluded: bool

class PoolEntry(_PoolEntryRequired, total=False):
    asset: str
    src_start: float
    src_end: float
    source_ids: SourceIds
    effect_id: str
    param_schema: dict[str, Any]
    defaults: dict[str, Any]
    meta: dict[str, Any]
    excluded_reason: str | None
    text: str
    speaker: str | None
    quote_kind: str
    motion_tags: list[str]
    mood_tags: list[str]
    subject: str
    camera: str
    intensity: float
    event_label: str
    bed_kind: str
    energy: float

class Pool(TypedDict, total=False):
    version: int
    generated_at: str
    source_slug: str
    entries: list[PoolEntry]

class ArrangementTextOverlay(TypedDict, total=False):
    content: str
    style_preset: str

ArrangementVisualRole = Literal["primary", "overlay", "stinger"]

class ArrangementAudioSource(TypedDict):
    pool_id: str
    trim_sub_range: list[float]

class _ArrangementVisualSourceRequired(TypedDict):
    pool_id: str
    role: ArrangementVisualRole

class ArrangementVisualSource(_ArrangementVisualSourceRequired, total=False):
    params: dict[str, Any]

class _ArrangementClipRequired(TypedDict):
    uuid: str
    order: int
    audio_source: ArrangementAudioSource | None
    visual_source: ArrangementVisualSource
    rationale: str

class ArrangementClip(_ArrangementClipRequired, total=False):
    text_overlay: ArrangementTextOverlay | None

class Arrangement(TypedDict, total=False):
    version: int
    generated_at: str
    brief_text: str
    target_duration_sec: float
    source_slug: str
    brief_slug: str
    pool_sha256: str
    brief_sha256: str
    clips: list[ArrangementClip]

class PipelineMetadataClipEntry(TypedDict, total=False):
    source_uuid: str
    caption_kind: Literal["dialogue", "visual"]
    picked_by: str
    pick_rationale: str
    pool_id: str | None
    pool_kind: PipelinePoolKind
    source_ids: SourceIds
    source_scene_id: str
    source_transcript_text: str | None
    arrangement_notes: str | None
    text_overlay_content: str
    score: float

class PipelineMetadata(TypedDict):
    version: int
    generated_at: str
    pipeline: dict[str, Any]
    clips: dict[str, PipelineMetadataClipEntry]
    sources: dict[str, dict[str, Any]]

# `from` is a Python keyword, so TimelineClip stores it as `from_` in memory and
# swaps to/from `"from"` at the JSON boundary. Every other field is 1:1 with TS.
_FROM_ALIAS = ("from_", "from")
_TIMELINE_TOP_ALLOWED = frozenset({"theme", "theme_overrides", "generation_defaults", "clips", "tracks", "pinnedShotGroups", "output"})
_THEME_OVERRIDES_ALLOWED = frozenset({"visual", "generation", "voice", "audio", "pacing"})
_CLIP_ALLOWED = frozenset(
    {
        "id", "at", "track", "clipType", "asset", "from", "to", "speed", "hold",
        "volume", "x", "y", "width", "height", "cropTop", "cropBottom",
        "cropLeft", "cropRight", "opacity", "params", "text", "entrance", "exit",
        "continuous", "transition", "effects", "source_uuid", "generation",
        "pool_id", "clip_order",
    }
)
_TRACK_ALLOWED = frozenset({"id", "kind", "label", "scale", "fit", "opacity", "volume", "muted", "blendMode"})
_ASSET_ENTRY_ALLOWED = frozenset(
    {
        "file",
        "url",
        "etag",
        "content_sha256",
        "url_expires_at",
        "type",
        "duration",
        "resolution",
        "fps",
        "generationId",
        "variantId",
        "thumbnailUrl",
    }
)
METADATA_VERSION = 1
POOL_VERSION = 1
ARRANGEMENT_VERSION = 1
# Fields here survive ffprobe cache hits. Run-specific fields (*_ref) must NOT be listed.
CARRY_FORWARD_SOURCE_FIELDS: frozenset[str] = frozenset({"codec"})
_POOL_ENTRY_ALLOWED = frozenset(
    {
        "id",
        "kind",
        "category",
        "asset",
        "src_start",
        "src_end",
        "duration",
        "source_ids",
        "scores",
        "excluded",
        "excluded_reason",
        "effect_id",
        "param_schema",
        "defaults",
        "meta",
        "text",
        "speaker",
        "quote_kind",
        "motion_tags",
        "mood_tags",
        "subject",
        "camera",
        "intensity",
        "event_label",
        "bed_kind",
        "energy",
    }
)
_POOL_ALLOWED = frozenset({"version", "generated_at", "source_slug", "entries"})
_SOURCE_IDS_ALLOWED = frozenset({"segment_ids", "scene_id"})
_POOL_SCORES_ALLOWED = frozenset({"triage", "deep", "quotability"})
_ARRANGEMENT_ALLOWED = frozenset(
    {
        "version",
        "generated_at",
        "brief_text",
        "target_duration_sec",
        "source_slug",
        "brief_slug",
        "pool_sha256",
        "brief_sha256",
        "clips",
    }
)
_ARRANGEMENT_CLIP_ALLOWED = frozenset({"uuid", "order", "audio_source", "visual_source", "text_overlay", "rationale"})
_ARRANGEMENT_AUDIO_SOURCE_ALLOWED = frozenset({"pool_id", "trim_sub_range"})
_ARRANGEMENT_VISUAL_SOURCE_ALLOWED = frozenset({"pool_id", "role", "params"})
_ARRANGEMENT_TEXT_OVERLAY_ALLOWED = frozenset({"content", "style_preset"})
_FORBIDDEN_ARRANGEMENT_TIME_KEYS = frozenset({"src_start", "src_end", "duration", "from", "to", "at", "start", "end", "time"})

def _write_json(path: Path, payload: Any) -> None:
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

def _raise_unknown_keys(path: str, payload: dict[str, Any], allowed: frozenset[str]) -> None:
    for key in payload:
        if key not in allowed:
            raise ValueError(f"{path} has unknown key {key!r}")

def _normalize_clip_for_validation(clip: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(clip)
    if "from_" in normalized and "from" not in normalized:
        normalized["from"] = normalized.pop("from_")
    return normalized

def _effect_ids(theme: str | None = None) -> set[str]:
    try:
        from . import effects_catalog
    except ImportError:
        import effects_catalog  # type: ignore[no-redef]
    return set(effects_catalog.list_effect_ids(theme=theme))

def _animation_ids() -> set[str]:
    try:
        from . import effects_catalog
    except ImportError:
        import effects_catalog  # type: ignore[no-redef]
    return set(effects_catalog.list_animation_ids())

def _transition_ids() -> set[str]:
    try:
        from . import effects_catalog
    except ImportError:
        import effects_catalog  # type: ignore[no-redef]
    return set(effects_catalog.list_transition_ids())

def _animation_meta(animation_id: str) -> dict[str, Any]:
    try:
        from . import effects_catalog
    except ImportError:
        import effects_catalog  # type: ignore[no-redef]
    try:
        return effects_catalog.read_animation_meta(animation_id)
    except Exception:
        return {}

def _validate_animation_reference(ref: Any, phase: str, path: str, known_ids: set[str]) -> None:
    if isinstance(ref, str):
        animation_id = ref
    elif isinstance(ref, dict):
        _raise_unknown_keys(path, ref, frozenset({"id", "durationFrames", "easing", "params"}))
        animation_id = ref.get("id")
        if "durationFrames" in ref and (
            not isinstance(ref.get("durationFrames"), (int, float)) or float(ref["durationFrames"]) <= 0
        ):
            raise ValueError(f"{path}.durationFrames must be a positive number")
        if "easing" in ref and not isinstance(ref.get("easing"), str):
            raise ValueError(f"{path}.easing must be a string")
        if "params" in ref and not isinstance(ref.get("params"), dict):
            raise ValueError(f"{path}.params must be an object")
    else:
        raise ValueError(f"{path} must be an animation id string or object")
    if not isinstance(animation_id, str) or not animation_id:
        raise ValueError(f"{path}.id must be a non-empty string")
    if known_ids and animation_id not in known_ids:
        raise ValueError(f"{path} animation id {animation_id!r} is not present in the animations catalog")
    meta = _animation_meta(animation_id)
    meta_phase = meta.get("phase")
    phase_matches = (
        meta_phase in (None, "any", phase)
        or (isinstance(meta_phase, list) and phase in meta_phase)
    )
    if not phase_matches:
        raise ValueError(f"{path} animation {animation_id!r} has phase {meta_phase!r}, expected {phase!r}")

def _validate_animation_reference_list(value: Any, phase: str, path: str, known_ids: set[str]) -> None:
    if value is None:
        return
    refs = value if isinstance(value, list) else [value]
    if not refs:
        raise ValueError(f"{path} must not be an empty animation list")
    for index, ref in enumerate(refs):
        _validate_animation_reference(ref, phase, f"{path}[{index}]", known_ids)

def _schema_params_for_animation_refs(schema: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Keep legacy strict effect schemas usable while standardized animation refs roll out."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return params
    next_params = dict(params)
    for phase in ("entrance", "sustain", "exit"):
        if phase not in next_params:
            continue
        prop = properties.get(phase)
        if not isinstance(prop, dict):
            next_params.pop(phase)
            continue
        enum = prop.get("enum")
        if isinstance(enum, list) and "none" in enum:
            next_params[phase] = "none"
        elif prop.get("type") == "string":
            next_params[phase] = "none"
    return next_params

def _validate_effect_params(effect_id: str, params: Any, path: str, theme: str | None = None) -> None:
    if params is None:
        return
    if not isinstance(params, dict):
        raise ValueError(f"{path} must be an object")
    known_animation_ids = _animation_ids()
    for phase in ("entrance", "sustain", "exit"):
        if phase in params:
            _validate_animation_reference_list(params[phase], phase, f"{path}.{phase}", known_animation_ids)
    try:
        from . import effects_catalog
        import jsonschema  # type: ignore[import-not-found]
    except ImportError:
        try:
            import effects_catalog  # type: ignore[no-redef]
            import jsonschema  # type: ignore[import-not-found,no-redef]
        except ImportError:
            return
    schema = effects_catalog.read_effect_schema(effect_id, theme=theme)
    jsonschema.validate(_schema_params_for_animation_refs(schema, params), schema)

def _transition_reference(value: Any, path: str) -> tuple[str, float | None]:
    if isinstance(value, str):
        return value, None
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a transition id string or object")
    _raise_unknown_keys(path, value, frozenset({"id", "type", "duration", "durationFrames", "params"}))
    transition_id = value.get("id", value.get("type"))
    if not isinstance(transition_id, str) or not transition_id:
        raise ValueError(f"{path}.id must be a non-empty string")
    if "params" in value and not isinstance(value.get("params"), dict):
        raise ValueError(f"{path}.params must be an object")
    duration_frames = value.get("durationFrames")
    duration_seconds = value.get("duration")
    if duration_frames is not None:
        if not isinstance(duration_frames, (int, float)) or float(duration_frames) <= 0:
            raise ValueError(f"{path}.durationFrames must be a positive number")
        return transition_id, float(duration_frames)
    if duration_seconds is not None:
        if not isinstance(duration_seconds, (int, float)) or float(duration_seconds) <= 0:
            raise ValueError(f"{path}.duration must be a positive number")
        return transition_id, None
    return transition_id, None

def _clip_duration_seconds(clip: dict[str, Any]) -> float | None:
    hold = clip.get("hold")
    if isinstance(hold, (int, float)) and float(hold) >= 0:
        return float(hold)
    start = clip.get("from", 0)
    end = clip.get("to")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and float(end) >= float(start):
        return float(end) - float(start)
    return None

def _validate_clip_transitions(clips: list[dict[str, Any]], fps: float) -> None:
    known_ids = _transition_ids()
    by_track: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, clip in enumerate(clips):
        track = clip.get("track")
        if isinstance(track, str):
            by_track.setdefault(track, []).append((index, clip))
    for track_clips in by_track.values():
        track_clips.sort(key=lambda item: float(item[1].get("at", 0)))
        for position, (index, clip) in enumerate(track_clips):
            if "transition" not in clip:
                continue
            transition_id, duration_frames = _transition_reference(clip["transition"], f"clips[{index}].transition")
            if known_ids and transition_id not in known_ids:
                raise ValueError(
                    f"clips[{index}].transition id {transition_id!r} is not present in the transitions catalog"
                )
            next_clip = track_clips[position + 1][1] if position + 1 < len(track_clips) else None
            current_duration = _clip_duration_seconds(clip)
            next_duration = _clip_duration_seconds(next_clip) if next_clip is not None else None
            duration_seconds = duration_frames / fps if duration_frames is not None else None
            if duration_seconds is None and isinstance(clip.get("transition"), dict):
                raw_duration = clip["transition"].get("duration")
                duration_seconds = float(raw_duration) if isinstance(raw_duration, (int, float)) else None
            if duration_seconds is None or current_duration is None or next_duration is None:
                continue
            if duration_seconds > current_duration or duration_seconds > next_duration:
                raise ValueError(
                    f"clips[{index}].transition duration {duration_seconds:.3f}s must fit both adjacent same-track clips"
                )

def _timeline_fps(config: dict[str, Any]) -> float:
    """Best-effort fps for timeline-internal validation (transitions, etc.).

    The authoritative fps comes from theme.visual.canvas at render time. This helper
    looks for a theme_overrides override; otherwise it returns a sentinel default
    (30) used only for clip-transition duration checks.
    """
    overrides = config.get("theme_overrides")
    if isinstance(overrides, dict):
        visual = overrides.get("visual")
        if isinstance(visual, dict):
            canvas = visual.get("canvas")
            if isinstance(canvas, dict):
                fps_value = canvas.get("fps")
                if isinstance(fps_value, (int, float)) and float(fps_value) > 0:
                    return float(fps_value)
    return 30.0


def _swap_from_load(clip: dict[str, Any]) -> dict[str, Any]:
    if "from" in clip:
        clip["from_"] = clip.pop("from")
    return clip

def _swap_from_dump(clip: dict[str, Any]) -> dict[str, Any]:
    out = dict(clip)
    if "from_" in out:
        out["from"] = out.pop("from_")
    return out

def _round_at_for_dump(clip: dict[str, Any]) -> dict[str, Any]:
    if "at" in clip and isinstance(clip["at"], (int, float)):
        clip["at"] = round(float(clip["at"]), 3)
    return clip

def merge_generation(
    theme_generation: dict[str, Any] | None,
    per_clip: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge per-clip generation atop the resolved theme.generation block.

    Per-clip keys win on conflict. Lists (references, assets) are replaced wholesale,
    not merged. Returns an empty dict if both inputs are empty/None.
    """
    merged: dict[str, Any] = {}
    if isinstance(theme_generation, dict):
        merged.update(theme_generation)
    if isinstance(per_clip, dict):
        merged.update(per_clip)
    return merged


def _deep_merge_theme(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge overlay onto base for theme blocks.

    Top-level theme keys (visual, generation, voice, audio, pacing) are merged at one
    level deep. Nested dicts inside (e.g. visual.canvas) are merged key-by-key. Lists
    such as generation.references and generation.assets are replaced wholesale.
    """
    result: dict[str, Any] = {key: value for key, value in base.items()}
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            merged_block: dict[str, Any] = dict(result[key])
            for sub_key, sub_value in value.items():
                if (
                    sub_key in merged_block
                    and isinstance(merged_block[sub_key], dict)
                    and isinstance(sub_value, dict)
                ):
                    inner = dict(merged_block[sub_key])
                    inner.update(sub_value)
                    merged_block[sub_key] = inner
                else:
                    merged_block[sub_key] = sub_value
            result[key] = merged_block
        else:
            result[key] = value
    return result


def resolve_timeline_theme(timeline: "TimelineConfig", themes_root: Path) -> dict[str, Any]:
    """Return the merged theme view: theme.json + timeline.theme_overrides.

    `timeline['theme']` is a slug resolved against `<themes_root>/<slug>/theme.json`.
    Overrides are deep-merged onto the loaded theme; list-valued fields (references,
    assets) are replaced wholesale by the override.
    """
    slug = timeline.get("theme") if isinstance(timeline, dict) else None
    if not isinstance(slug, str) or not slug:
        raise ValueError("Timeline.theme must be a non-empty slug")
    theme_path = Path(themes_root) / slug / "theme.json"
    if not theme_path.is_file():
        raise FileNotFoundError(f"Theme {slug!r} not found at {theme_path}")
    base = json.loads(theme_path.read_text(encoding="utf-8"))
    if not isinstance(base, dict):
        raise ValueError(f"Theme file {theme_path} must contain a JSON object")
    overrides = timeline.get("theme_overrides") if isinstance(timeline, dict) else None
    if isinstance(overrides, dict) and overrides:
        return _deep_merge_theme(base, overrides)
    return base

def load_timeline(path: Path) -> TimelineConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_timeline(data)
    data["clips"] = [_swap_from_load(dict(clip)) for clip in data["clips"]]
    return data  # type: ignore[return-value]

def save_timeline(config: TimelineConfig, path: Path) -> None:
    payload: dict[str, Any] = dict(config)
    payload["clips"] = [_round_at_for_dump(_swap_from_dump(dict(clip))) for clip in payload["clips"]]
    validate_timeline(payload)
    _write_json(path, payload)

def load_registry(path: Path) -> AssetRegistry:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_registry(data)
    return data  # type: ignore[return-value]

def save_registry(registry: AssetRegistry, path: Path) -> None:
    validate_registry(registry)
    _write_json(path, registry)

def load_metadata(path: Path) -> PipelineMetadata:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_metadata(data)
    return data  # type: ignore[return-value]

def save_metadata(meta: PipelineMetadata, path: Path) -> None:
    validate_metadata(meta)
    _write_json(path, meta)

def load_pool(path: Path) -> Pool:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_pool(data)
    return data  # type: ignore[return-value]

def save_pool(pool: Pool, path: Path) -> None:
    validate_pool(pool)
    _write_json(path, pool)

def _assign_missing_arrangement_uuids(arrangement: Any) -> bool:
    if not isinstance(arrangement, dict):
        return False
    clips = arrangement.get("clips")
    if not isinstance(clips, list):
        return False
    used = {
        clip.get("uuid")
        for clip in clips
        if isinstance(clip, dict) and isinstance(clip.get("uuid"), str)
    }
    assigned = False
    for clip in clips:
        if not isinstance(clip, dict) or "uuid" in clip:
            continue
        value = uuid.uuid4().hex[:8]
        while value in used:
            value = uuid.uuid4().hex[:8]
        used.add(value)
        clip["uuid"] = value
        assigned = True
        order = clip.get("order")
        print(f"timeline.load_arrangement: migrated clip order={order} uuid={value}", file=sys.stderr)
    return assigned

def load_arrangement(
    path: Path,
    pool_ids: set[str] | None = None,
    *,
    assign_missing_uuids: bool = False,
) -> Arrangement:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    migrated = False
    if assign_missing_uuids:
        migrated = _assign_missing_arrangement_uuids(data)
    validate_arrangement(data, pool_ids)
    if migrated:
        _write_json(Path(path), data)
    return data  # type: ignore[return-value]

def save_arrangement(arrangement: Arrangement, path: Path, pool_ids: set[str] | None = None) -> None:
    validate_arrangement(arrangement, pool_ids)
    _write_json(path, arrangement)

def validate_registry(registry: Any) -> None:
    if not isinstance(registry, dict):
        raise ValueError("Asset registry must be a JSON object")
    _raise_unknown_keys("Asset registry", registry, frozenset({"assets"}))
    assets = registry.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("Asset registry.assets must be an object")
    for key, entry in assets.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Asset registry.assets[{key!r}] must be an object")
        _raise_unknown_keys(f"Asset registry.assets[{key!r}]", entry, _ASSET_ENTRY_ALLOWED)
        if "file" not in entry and "url" not in entry:
            raise ValueError(f"Asset {key!r} must have 'file' or 'url'")
        url = entry.get("url")
        if url is not None and (not isinstance(url, str) or not url.startswith(("http://", "https://"))):
            raise ValueError(f"Asset {key!r}.url must be an http(s) URL")
        content_sha256 = entry.get("content_sha256")
        if content_sha256 is not None and (
            not isinstance(content_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None
        ):
            raise ValueError(f"Asset {key!r}.content_sha256 must be a 64-character lowercase hex string")
        if "url_expires_at" in entry:
            _validate_generated_at(entry.get("url_expires_at"), f"Asset {key!r}.url_expires_at")
        etag = entry.get("etag")
        if etag is not None and (not isinstance(etag, str) or not etag):
            raise ValueError(f"Asset {key!r}.etag must be a non-empty string")

def validate_timeline(config: Any, *, strict: bool = True) -> None:
    """Validate a Banodoco timeline.

    Sprint 5 (SD-015): `strict` defaults to True. The strict path requires
    every clip's `clipType` to be in the registered effect set (workspace
    effects + active-theme effects discovered via
    tools/effects_catalog.py:139-155). This catches authoring of unknown
    clipTypes at validate-time; the loud-placeholder Sprint-3 fallback in
    Reigh's TimelineRenderer is the runtime safety net for the
    "installed but unrenderable" case.

    Callers that need to accept legacy/under-construction timelines (e.g.
    in-flight pipeline outputs that reference theme content not yet on
    disk) can opt into `strict=False`.
    """
    if not isinstance(config, dict):
        raise ValueError("Timeline must be a JSON object")
    # Shape-check against the shared JSON Schema first; then run the
    # Banodoco-only semantic checks (effect-id registry, transition durations).
    normalized_for_shared = dict(config)
    if isinstance(normalized_for_shared.get("clips"), list):
        normalized_for_shared["clips"] = [
            _normalize_clip_for_validation(c) if isinstance(c, dict) else c
            for c in normalized_for_shared["clips"]
        ]
    _shared_validate_timeline(normalized_for_shared, strict=strict)
    _raise_unknown_keys("Timeline", config, _TIMELINE_TOP_ALLOWED)
    theme = config.get("theme")
    if not isinstance(theme, str) or not theme:
        raise ValueError("Timeline.theme must be a non-empty slug")
    fps = _timeline_fps(config)
    tracks = config.get("tracks")
    if tracks is not None:
        if not isinstance(tracks, list):
            raise ValueError("Timeline.tracks must be a list")
        for index, track in enumerate(tracks):
            if not isinstance(track, dict):
                raise ValueError(f"tracks[{index}] must be an object")
            _raise_unknown_keys(f"tracks[{index}]", track, _TRACK_ALLOWED)
            for field in ("id", "kind", "label"):
                if field not in track:
                    raise ValueError(f"tracks[{index}].{field} is required")
    overrides = config.get("theme_overrides")
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError("Timeline.theme_overrides must be an object")
        _raise_unknown_keys("Timeline.theme_overrides", overrides, _THEME_OVERRIDES_ALLOWED)
    clips = config.get("clips")
    if not isinstance(clips, list):
        raise ValueError("Timeline.clips must be a list")
    clip_ids: set[str] = set()
    normalized_clips: list[dict[str, Any]] = []
    for index, clip_raw in enumerate(clips):
        if not isinstance(clip_raw, dict):
            raise ValueError(f"clips[{index}] must be an object")
        clip = _normalize_clip_for_validation(clip_raw)
        normalized_clips.append(clip)
        _raise_unknown_keys(f"clips[{index}]", clip, _CLIP_ALLOWED)
        for field in ("id", "at", "track"):
            if field not in clip:
                raise ValueError(f"clips[{index}].{field} is required")
        clip_type = clip.get("clipType", "media")
        if not isinstance(clip_type, str):
            raise ValueError(f"clips[{index}].clipType must be a string")
        # Sprint 5 strict mode: active theme slug from the timeline so the
        # effect-id scan picks up theme-scoped clipTypes (e.g. 2rp's
        # section-hook). When strict=False, an unknown clipType still
        # raises this same error (the registry scan is mandatory) — the
        # `strict` flag controls the upstream JSON-Schema check.
        active_theme = theme if isinstance(theme, str) else None
        effect_ids = _effect_ids(active_theme)
        if clip_type not in set(BUILTIN_CLIP_TYPES) | effect_ids:
            raise ValueError(f"clips[{index}].clipType {clip_type!r} is not a built-in clip type or effect id")
        if clip_type in effect_ids:
            _validate_effect_params(clip_type, clip.get("params"), f"clips[{index}].params", theme=active_theme)
        if "pool_id" in clip and not isinstance(clip["pool_id"], str):
            raise ValueError(f"clips[{index}].pool_id must be a string")
        if "clip_order" in clip:
            order = clip["clip_order"]
            if not isinstance(order, int) or isinstance(order, bool) or order <= 0:
                raise ValueError(f"clips[{index}].clip_order must be a positive integer")
        if clip["id"] in clip_ids:
            raise ValueError(f"clips[{index}].id {clip['id']!r} is not unique")
        clip_ids.add(clip["id"])
    _validate_clip_transitions(normalized_clips, float(fps))

def validate_metadata(meta: Any) -> None:
    if not isinstance(meta, dict):
        raise ValueError("Metadata must be a JSON object")
    if meta.get("version") != METADATA_VERSION:
        raise ValueError(f"Metadata.version must be {METADATA_VERSION}")
    generated_at = meta.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at or not generated_at.endswith("Z"):
        raise ValueError("Metadata.generated_at must be a non-empty UTC timestamp ending in 'Z'")
    for field in ("pipeline", "clips", "sources"):
        value = meta.get(field)
        if not isinstance(value, dict):
            raise ValueError(f"Metadata.{field} must be an object")
    for clip_id, clip_meta in meta["clips"].items():
        if not isinstance(clip_meta, dict):
            raise ValueError(f"Metadata.clips[{clip_id!r}] must be an object")
    for source_key, source_meta in meta["sources"].items():
        if not isinstance(source_meta, dict):
            raise ValueError(f"Metadata.sources[{source_key!r}] must be an object")

def _validate_generated_at(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value or not value.endswith("Z"):
        raise ValueError(f"{path} must be a non-empty UTC timestamp ending in 'Z'")

def _validate_source_ids(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    _raise_unknown_keys(path, value, _SOURCE_IDS_ALLOWED)
    segment_ids = value.get("segment_ids")
    if segment_ids is not None:
        if not isinstance(segment_ids, list) or not all(isinstance(segment_id, int) for segment_id in segment_ids):
            raise ValueError(f"{path}.segment_ids must be a list of integers")
    scene_id = value.get("scene_id")
    if scene_id is not None and not isinstance(scene_id, str):
        raise ValueError(f"{path}.scene_id must be a string")

def _validate_pool_scores(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    _raise_unknown_keys(path, value, _POOL_SCORES_ALLOWED)
    for key, score in value.items():
        if not isinstance(score, (int, float)):
            raise ValueError(f"{path}.{key} must be numeric")

def validate_pool(pool: Any) -> None:
    if not isinstance(pool, dict):
        raise ValueError("Pool must be a JSON object")
    _raise_unknown_keys("Pool", pool, _POOL_ALLOWED)
    if pool.get("version") != POOL_VERSION:
        raise ValueError(f"Pool.version must be {POOL_VERSION}")
    _validate_generated_at(pool.get("generated_at"), "Pool.generated_at")
    source_slug = pool.get("source_slug")
    if source_slug is not None and not isinstance(source_slug, str):
        raise ValueError("Pool.source_slug must be a string")
    entries = pool.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Pool.entries must be a list")
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        path = f"Pool.entries[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{path} must be an object")
        _raise_unknown_keys(path, entry, _POOL_ENTRY_ALLOWED)
        for field in ("id", "kind", "category", "duration", "scores", "excluded"):
            if field not in entry:
                raise ValueError(f"{path}.{field} is required")
        entry_id = entry["id"]
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError(f"{path}.id must be a non-empty string")
        if entry_id in seen_ids:
            raise ValueError(f"{path}.id {entry_id!r} is not unique")
        seen_ids.add(entry_id)
        if entry.get("kind") not in {"source", "generative"}:
            raise ValueError(f"{path}.kind must be one of source, generative")
        if entry.get("category") not in {"dialogue", "visual", "reaction", "applause", "music"}:
            raise ValueError(f"{path}.category must be one of dialogue, visual, reaction, applause, music")
        _validate_pool_scores(entry["scores"], f"{path}.scores")
        if not isinstance(entry.get("excluded"), bool):
            raise ValueError(f"{path}.excluded must be a boolean")
        excluded_reason = entry.get("excluded_reason")
        if excluded_reason is not None and not isinstance(excluded_reason, str):
            raise ValueError(f"{path}.excluded_reason must be a string or null")
        if entry["kind"] == "source":
            for field in ("asset", "src_start", "src_end", "duration", "source_ids"):
                if field not in entry:
                    raise ValueError(f"{path}.{field} is required for source entries")
            if not isinstance(entry.get("asset"), str) or not entry["asset"]:
                raise ValueError(f"{path}.asset must be a non-empty string")
            for field in ("src_start", "src_end", "duration"):
                if not isinstance(entry.get(field), (int, float)):
                    raise ValueError(f"{path}.{field} must be numeric")
            if float(entry["src_start"]) < 0 or float(entry["src_end"]) < 0 or float(entry["duration"]) < 0:
                raise ValueError(f"{path} timing values must be non-negative")
            if float(entry["src_end"]) < float(entry["src_start"]):
                raise ValueError(f"{path}.src_end must be >= src_start")
            _validate_source_ids(entry["source_ids"], f"{path}.source_ids")
        else:
            for field in ("effect_id", "param_schema", "defaults", "meta"):
                if field not in entry:
                    raise ValueError(f"{path}.{field} is required for generative entries")
            if entry.get("duration") is not None:
                raise ValueError(f"{path}.duration must be null for generative entries")
            effect_id = entry.get("effect_id")
            if not isinstance(effect_id, str) or not effect_id:
                raise ValueError(f"{path}.effect_id must be a non-empty string")
            if effect_id not in _effect_ids():
                raise ValueError(f"{path}.effect_id {effect_id!r} is not present in the effects catalog")
            for field in ("param_schema", "defaults", "meta"):
                if not isinstance(entry.get(field), dict):
                    raise ValueError(f"{path}.{field} must be an object")

def _reject_forbidden_arrangement_time_keys(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _FORBIDDEN_ARRANGEMENT_TIME_KEYS:
                raise ValueError(f"{path} contains forbidden time key {key!r}")
            _reject_forbidden_arrangement_time_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_arrangement_time_keys(child, f"{path}[{index}]")

class ArrangementDurationError(ValueError):
    """Raised when a caller opts into the source-cut duration window."""

def validate_arrangement_duration_window(
    arrangement: Any,
    *,
    min_sec: float = 75.0,
    max_sec: float = 90.0,
) -> None:
    target_duration_sec = arrangement.get("target_duration_sec") if isinstance(arrangement, dict) else None
    if not isinstance(target_duration_sec, (int, float)):
        raise ArrangementDurationError("Arrangement.target_duration_sec must be numeric")
    if not min_sec <= float(target_duration_sec) <= max_sec:
        raise ArrangementDurationError(
            f"Arrangement.target_duration_sec must be between {min_sec:.1f} and {max_sec:.1f} seconds"
        )

def is_all_generative_arrangement(arrangement: Any, pool: Any) -> bool:
    if not isinstance(arrangement, dict) or not isinstance(pool, dict):
        return False
    entries = {
        entry.get("id"): entry
        for entry in pool.get("entries", [])
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    referenced: set[str] = set()
    for clip in arrangement.get("clips", []):
        if not isinstance(clip, dict):
            continue
        for key in ("audio_source", "visual_source"):
            source = clip.get(key)
            if isinstance(source, dict) and isinstance(source.get("pool_id"), str):
                referenced.add(source["pool_id"])
    if not referenced:
        return False
    return all(isinstance(entries.get(pool_id), dict) and entries[pool_id].get("kind") == "generative" for pool_id in referenced)

def validate_arrangement(arrangement: Any, pool_ids: set[str] | None = None) -> None:
    if not isinstance(arrangement, dict):
        raise ValueError("Arrangement must be a JSON object")
    _raise_unknown_keys("Arrangement", arrangement, _ARRANGEMENT_ALLOWED)
    if arrangement.get("version") != ARRANGEMENT_VERSION:
        raise ValueError(f"Arrangement.version must be {ARRANGEMENT_VERSION}")
    _validate_generated_at(arrangement.get("generated_at"), "Arrangement.generated_at")
    brief_text = arrangement.get("brief_text")
    if not isinstance(brief_text, str) or not brief_text:
        raise ValueError("Arrangement.brief_text must be a non-empty string")
    target_duration_sec = arrangement.get("target_duration_sec")
    if not isinstance(target_duration_sec, (int, float)):
        raise ValueError("Arrangement.target_duration_sec must be numeric")
    for field in ("source_slug", "brief_slug", "pool_sha256", "brief_sha256"):
        value = arrangement.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Arrangement.{field} must be a string")
    clips = arrangement.get("clips")
    if not isinstance(clips, list):
        raise ValueError("Arrangement.clips must be a list")
    allowed_ids = set(pool_ids) if pool_ids is not None else None
    seen_orders: set[int] = set()
    seen_uuids: set[str] = set()
    audio_ranges_by_pool: dict[str, list[tuple[float, float, int]]] = {}
    for index, clip in enumerate(clips):
        path = f"Arrangement.clips[{index}]"
        if not isinstance(clip, dict):
            raise ValueError(f"{path} must be an object")
        _raise_unknown_keys(path, clip, _ARRANGEMENT_CLIP_ALLOWED)
        _reject_forbidden_arrangement_time_keys(clip, path)
        for field in ("uuid", "order", "audio_source", "visual_source", "rationale"):
            if field not in clip:
                raise ValueError(f"{path}.{field} is required")
        clip_uuid = clip["uuid"]
        if not isinstance(clip_uuid, str) or re.fullmatch(r"[0-9a-f]{8}", clip_uuid) is None:
            raise ValueError(f"{path}.uuid must be an 8-character lowercase hex string")
        if clip_uuid in seen_uuids:
            raise ValueError(f"{path}.uuid {clip_uuid!r} is not unique")
        seen_uuids.add(clip_uuid)
        order = clip["order"]
        if not isinstance(order, int) or order <= 0:
            raise ValueError(f"{path}.order must be a positive integer")
        if order in seen_orders:
            raise ValueError(f"{path}.order {order} is not unique")
        seen_orders.add(order)
        audio_source = clip.get("audio_source")
        if audio_source is not None:
            if not isinstance(audio_source, dict):
                raise ValueError(f"{path}.audio_source must be an object or null")
            _raise_unknown_keys(f"{path}.audio_source", audio_source, _ARRANGEMENT_AUDIO_SOURCE_ALLOWED)
            pool_id = audio_source.get("pool_id")
            if not isinstance(pool_id, str) or not pool_id:
                raise ValueError(f"{path}.audio_source.pool_id must be a non-empty string")
            if allowed_ids is not None and pool_id not in allowed_ids:
                raise ValueError(f"{path}.audio_source.pool_id {pool_id!r} is not present in the pool")
            trim_sub_range = audio_source.get("trim_sub_range")
            if not isinstance(trim_sub_range, list) or len(trim_sub_range) != 2:
                raise ValueError(f"{path}.audio_source.trim_sub_range must be a 2-item list")
            if not all(isinstance(value, (int, float)) for value in trim_sub_range):
                raise ValueError(f"{path}.audio_source.trim_sub_range entries must be numeric")
            if float(trim_sub_range[1]) <= float(trim_sub_range[0]):
                raise ValueError(f"{path}.audio_source.trim_sub_range must have end > start")
            audio_ranges_by_pool.setdefault(pool_id, []).append(
                (float(trim_sub_range[0]), float(trim_sub_range[1]), order)
            )
        visual_source = clip["visual_source"]
        if visual_source is None:
            if audio_source is None:
                raise ValueError(f"{path}.visual_source must be set when audio_source is null (stinger needs a visual)")
        else:
            if not isinstance(visual_source, dict):
                raise ValueError(f"{path}.visual_source must be an object or null")
            _raise_unknown_keys(f"{path}.visual_source", visual_source, _ARRANGEMENT_VISUAL_SOURCE_ALLOWED)
            visual_pool_id = visual_source.get("pool_id")
            if not isinstance(visual_pool_id, str) or not visual_pool_id:
                raise ValueError(f"{path}.visual_source.pool_id must be a non-empty string")
            if allowed_ids is not None and visual_pool_id not in allowed_ids:
                raise ValueError(f"{path}.visual_source.pool_id {visual_pool_id!r} is not present in the pool")
            role = visual_source.get("role")
            if role not in {"primary", "overlay", "stinger"}:
                raise ValueError(f"{path}.visual_source.role must be one of primary, overlay, stinger")
            params = visual_source.get("params")
            if params is not None and not isinstance(params, dict):
                raise ValueError(f"{path}.visual_source.params must be an object")
        text_overlay = clip.get("text_overlay")
        if text_overlay is not None:
            if not isinstance(text_overlay, dict):
                raise ValueError(f"{path}.text_overlay must be an object or null")
            _raise_unknown_keys(f"{path}.text_overlay", text_overlay, _ARRANGEMENT_TEXT_OVERLAY_ALLOWED)
            content = text_overlay.get("content")
            if not isinstance(content, str) or not content:
                raise ValueError(f"{path}.text_overlay.content must be a non-empty string")
            style_preset = text_overlay.get("style_preset")
            if style_preset is not None and not isinstance(style_preset, str):
                raise ValueError(f"{path}.text_overlay.style_preset must be a string")
        rationale = clip.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f"{path}.rationale must be a non-empty string")
    for pool_id, ranges in audio_ranges_by_pool.items():
        prev_start = prev_end = None
        prev_order = None
        for trim_start, trim_end, order in sorted(ranges, key=lambda item: item[0]):
            if prev_end is not None and prev_order is not None and prev_end > trim_start + 1e-3:
                raise ValueError(
                    f"Arrangement clips {prev_order} and {order} overlap on "
                    f"audio_source.pool_id {pool_id!r}: "
                    f"[{prev_start:.3f}, {prev_end:.3f}] vs [{trim_start:.3f}, {trim_end:.3f}]"
                )
            prev_start, prev_end, prev_order = trim_start, trim_end, order
