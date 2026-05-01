#!/usr/bin/env python3
"""Assemble selected source-video ranges into hype-cut planning files and optional rendered outputs using transcript, scene, and shot inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import asset_cache
from .audit import AuditContext
from .arrangement_rules import compile_arrangement_plan
from .theme_schema import load_theme, theme_root
from ._paths import PACKAGE_ROOT, REPO_ROOT, WORKSPACE_ROOT
from .timeline import (
    AssetRegistry,
    CARRY_FORWARD_SOURCE_FIELDS,
    METADATA_VERSION,
    PipelineMetadata,
    TimelineConfig,
    load_arrangement,
    load_metadata,
    load_pool,
    load_registry,
    load_timeline,
    materialize_output,
    save_metadata,
    save_registry,
    save_timeline,
    is_all_generative_arrangement,
    validate_arrangement_duration_window,
)

_FFPROBE_VERBOSE = False
_LEGACY_DEFAULT_CLIP_SEC = 4.0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan or render a hype cut from scene, shot, and transcript inputs.")
    parser.add_argument("--scenes", type=Path, help="Path to scenes.json.")
    parser.add_argument("--timeline", type=Path, help="Existing hype.timeline.json to resume from.")
    parser.add_argument("--assets", type=Path, help="Asset registry to use with --timeline (defaults to <timeline_dir>/hype.assets.json).")
    parser.add_argument("--video", type=str, help="Source video file.")
    parser.add_argument("--audio", type=str, help="Optional rant audio file for audio-backed pure-generative mode.")
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help=(
            "Output directory. Writes hype.edl.csv, hype.timeline.json, "
            "hype.assets.json, and hype.metadata.json."
        ),
    )
    parser.add_argument("--transcript", type=Path, help="Transcript JSON used for arrangement metadata.")
    parser.add_argument("--shots", type=Path, help="Optional shots.json for future enrichment.")
    parser.add_argument("--arrangement", type=Path, help="Arrangement JSON for pool-based multitrack assembly.")
    parser.add_argument("--pool", type=Path, help="Pool JSON used with --arrangement.")
    parser.add_argument("--brief", type=Path, help="brief.txt used with --arrangement.")
    parser.add_argument("--theme", help="Theme id, theme directory, or path to theme.json.")
    parser.add_argument("--asset", action="append", default=[], help="Additional source asset mapping in KEY=PATH form.")
    parser.add_argument("--verbose", action="store_true", help="Print ffprobe cache activity.")
    parser.add_argument(
        "--primary-asset",
        help=(
            "Asset key that the --scenes / --transcript / --shots CLI inputs describe. "
            "Defaults to main when that key exists (single-source and plain-text picks). "
            "For multi-source JSON picks without a main key, this flag is required."
        ),
    )
    parser.add_argument(
        "--renderer",
        choices=["remotion"],
        default="remotion",
        help="Render backend. remotion (default) uses tools/remotion/.",
    )
    parser.add_argument("--render", action="store_true", help="Render clips and concat them into hype.mp4.")
    return parser

def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_theme_path(theme_value: str | None) -> Path | None:
    if theme_value is None:
        return None
    candidate = Path(theme_value)
    if candidate.name == "theme.json":
        return candidate
    if candidate.exists() and candidate.is_dir():
        return candidate / "theme.json"
    if candidate.exists():
        return candidate
    return WORKSPACE_ROOT / "themes" / theme_value / "theme.json"


def _theme_slug_from_path(theme_path: Path | None) -> str | None:
    """Derive the theme slug (directory name) from a theme.json or theme dir path."""
    if theme_path is None:
        return None
    path = Path(theme_path)
    if path.name == "theme.json":
        return path.parent.name
    if path.is_dir():
        return path.name
    return path.parent.name


def _theme_default_clip_sec(theme: dict[str, Any] | None) -> float | None:
    pacing = theme.get("pacing") if isinstance(theme, dict) else None
    value = pacing.get("default_clip_sec") if isinstance(pacing, dict) else None
    return float(value) if isinstance(value, (int, float)) else None


# Effects whose animation arrays should be sourced from the theme/effect
# defaults.json — never from the LLM brief output. The brief's job is content,
# not styling. New branded effects should be added here as they're authored.
_BRANDED_EFFECT_IDS = frozenset({"section-hook", "art-card", "resource-card", "cta-card"})


def _drop_brand_animation_overrides(effect_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Remove entrance/exit/sustain keys from params for branded effects.

    For branded effects, the theme's effect defaults.json is authoritative. The LLM
    brief sometimes proposes entrance/exit arrays anyway; we silently drop them
    rather than threading them through to the timeline.
    """
    if effect_id not in _BRANDED_EFFECT_IDS or not params:
        return params
    return {key: value for key, value in params.items() if key not in {"entrance", "exit", "sustain"}}


def arrangement_uses_generative_visuals(arrangement: dict[str, Any], pool: dict[str, Any]) -> bool:
    generative_ids = {
        entry["id"]
        for entry in pool.get("entries", [])
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry.get("kind") == "generative"
    }
    for clip in arrangement.get("clips", []):
        visual_source = clip.get("visual_source") if isinstance(clip, dict) else None
        if isinstance(visual_source, dict) and visual_source.get("pool_id") in generative_ids:
            return True
    return False


def load_scenes(path: Path) -> list[dict[str, Any]]:
    data = load_json(path)
    if not isinstance(data, list):
        raise SystemExit(f"Expected a JSON list in {path}")
    return data

def load_transcript_segments(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None:
        return None
    data = load_json(path)
    segments = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(segments, list):
        raise SystemExit(f"Expected transcript segments in {path}")
    return segments

def parse_ffprobe_fps(value: Any, *, path: Path | str) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"ffprobe did not return fps for {path}")
    if "/" in value:
        numerator_text, denominator_text = value.split("/", 1)
        numerator = float(numerator_text)
        denominator = float(denominator_text)
        if denominator == 0:
            raise SystemExit(f"ffprobe returned invalid fps {value!r} for {path}")
        return numerator / denominator
    return float(value)

def probe_asset(path: Path | str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_name,width,height,avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid ffprobe JSON for {path}: {exc.msg}") from exc

    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise SystemExit(f"ffprobe did not return streams for {path}")
    stream = next((item for item in streams if isinstance(item, dict) and item.get("width") and item.get("height")), None)
    kind = "video"
    if stream is None:
        stream = next((item for item in streams if isinstance(item, dict) and isinstance(item.get("codec_name"), str)), None)
        kind = "audio"
    if stream is None:
        raise SystemExit(f"ffprobe did not return a usable stream for {path}")
    format_info = payload.get("format")
    if not isinstance(format_info, dict):
        raise SystemExit(f"ffprobe did not return format metadata for {path}")

    try:
        duration = float(format_info["duration"])
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"ffprobe returned incomplete metadata for {path}") from exc

    codec = stream.get("codec_name")
    if not isinstance(codec, str) or not codec:
        raise SystemExit(f"ffprobe did not return a codec for {path}")

    if kind == "video":
        fps_source = stream.get("avg_frame_rate")
        if fps_source in (None, "", "0/0"):
            fps_source = stream.get("r_frame_rate")
        fps = parse_ffprobe_fps(fps_source, path=path)
        resolution = f"{width}x{height}"
    else:
        fps = 0.0
        resolution = ""
    return {
        "type": kind,
        "duration": duration,
        "resolution": resolution,
        "fps": fps,
        "codec": codec,
    }

def probe_video_duration(video_path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())

def resolve_asset_paths(args: Any) -> tuple[dict[str, Path], dict[str, str]]:
    asset_paths: dict[str, Path] = {}
    asset_urls: dict[str, str] = {}
    raw_assets = getattr(args, "asset", None) or []
    for raw_entry in raw_assets:
        if not isinstance(raw_entry, str) or "=" not in raw_entry:
            raise SystemExit(f"Invalid --asset value {raw_entry!r}: expected KEY=PATH")
        key, raw_path = raw_entry.split("=", 1)
        if not key or not raw_path:
            raise SystemExit(f"Invalid --asset value {raw_entry!r}: expected KEY=PATH")
        if key in asset_paths or key in asset_urls:
            raise SystemExit(f"Duplicate asset key {key!r} in --asset")
        if asset_cache.is_url(raw_path):
            asset_urls[key] = raw_path
        else:
            asset_paths[key] = Path(raw_path).resolve()

    video_path = getattr(args, "video", None)
    if video_path is not None:
        if "main" in asset_paths or "main" in asset_urls:
            raise SystemExit("Duplicate asset key 'main': provided by both --asset and --video")
        if asset_cache.is_url(video_path):
            asset_urls["main"] = video_path
        else:
            asset_paths["main"] = Path(video_path).resolve()
    audio_path = getattr(args, "audio", None)
    if audio_path is not None and video_path is None:
        if "rant" in asset_paths or "rant" in asset_urls:
            raise SystemExit("Duplicate asset key 'rant': provided by both --asset and --audio")
        if asset_cache.is_url(audio_path):
            asset_urls["rant"] = audio_path
        else:
            asset_paths["rant"] = Path(audio_path).resolve()
    return asset_paths, asset_urls

def _url_cache_meta(url: str) -> dict[str, Any]:
    cache_path = asset_cache._path_for(url)
    if not cache_path.exists():
        return {}
    return asset_cache._read_meta(cache_path)

def build_registry(
    asset_paths: dict[str, Path],
    asset_urls: dict[str, str],
    existing_registry: AssetRegistry,
    prior_meta: dict[str, Any] | None,
) -> tuple[AssetRegistry, dict[str, dict[str, Any]]]:
    registry: AssetRegistry = {"assets": {}}
    sources_meta: dict[str, dict[str, Any]] = {}
    existing_assets = existing_registry.get("assets", {})
    prior_sources = (prior_meta or {}).get("sources", {})
    for key, url in asset_urls.items():
        existing_entry = existing_assets.get(key) if isinstance(existing_assets, dict) else None
        cache_hit = isinstance(existing_entry, dict) and existing_entry.get("url") == url and (
            (
                existing_entry.get("type") == "audio"
                and existing_entry.get("duration") is not None
            )
            or (
                existing_entry.get("duration") is not None
                and existing_entry.get("resolution") not in (None, "")
                and existing_entry.get("fps") is not None
            )
        )
        prior_source = prior_sources.get(key, {}) if isinstance(prior_sources, dict) else {}
        if not isinstance(prior_source, dict):
            prior_source = {}
        carried = {field: prior_source[field] for field in CARRY_FORWARD_SOURCE_FIELDS if field in prior_source}
        sources_meta[key] = dict(carried)
        cache_meta = _url_cache_meta(url)

        if cache_hit:
            if _FFPROBE_VERBOSE:
                print(f"ffprobe SKIP {key}")
            entry: dict[str, Any] = {
                "url": url,
                "duration": existing_entry["duration"],
                "type": existing_entry.get("type", "video"),
            }
            if entry["type"] != "audio":
                entry["resolution"] = existing_entry["resolution"]
                entry["fps"] = existing_entry["fps"]
            for field in ("content_sha256", "etag"):
                value = cache_meta.get(field, existing_entry.get(field))
                if isinstance(value, str) and value:
                    entry[field] = value
            registry["assets"][key] = entry
            continue

        if _FFPROBE_VERBOSE:
            print(f"ffprobe RUN {key}")
        probed = probe_asset(url)
        probed_type = probed.get("type", "video")
        entry = {
            "url": url,
            "duration": probed["duration"],
            "type": probed_type,
        }
        if probed_type != "audio":
            entry["resolution"] = probed["resolution"]
            entry["fps"] = probed["fps"]
        for field in ("content_sha256", "etag"):
            value = cache_meta.get(field)
            if isinstance(value, str) and value:
                entry[field] = value
        registry["assets"][key] = entry
        sources_meta[key]["codec"] = probed["codec"]

    for key, path in asset_paths.items():
        resolved_path = path.resolve()
        existing_entry = existing_assets.get(key) if isinstance(existing_assets, dict) else None
        cache_hit = (
            isinstance(existing_entry, dict)
            and existing_entry.get("file") == str(resolved_path)
            and existing_entry.get("duration") is not None
            and (
                existing_entry.get("type") == "audio"
                or (existing_entry.get("resolution") not in (None, "") and existing_entry.get("fps") is not None)
            )
        )
        prior_source = prior_sources.get(key, {}) if isinstance(prior_sources, dict) else {}
        if not isinstance(prior_source, dict):
            prior_source = {}
        carried = {field: prior_source[field] for field in CARRY_FORWARD_SOURCE_FIELDS if field in prior_source}
        sources_meta[key] = dict(carried)

        if cache_hit:
            if _FFPROBE_VERBOSE:
                print(f"ffprobe SKIP {key}")
            registry["assets"][key] = {
                "file": str(resolved_path),
                "duration": existing_entry["duration"],
                "type": existing_entry.get("type", "video"),
            }
            if registry["assets"][key]["type"] != "audio":
                registry["assets"][key]["resolution"] = existing_entry["resolution"]
                registry["assets"][key]["fps"] = existing_entry["fps"]
            continue

        if _FFPROBE_VERBOSE:
            print(f"ffprobe RUN {key}")
        probed = probe_asset(resolved_path)
        probed_type = probed.get("type", "video")
        registry["assets"][key] = {
            "file": str(resolved_path),
            "duration": probed["duration"],
            "type": probed_type,
        }
        if probed_type != "audio":
            registry["assets"][key]["resolution"] = probed["resolution"]
            registry["assets"][key]["fps"] = probed["fps"]
        sources_meta[key]["codec"] = probed["codec"]
    return registry, sources_meta

def _tool_fingerprints(tools_dir: Path) -> dict[str, str]:
    # Short sha1 of each tool's source bytes — enough to detect "same code ran
    # this clip" without leaking filesystem paths or pretending to be semver.
    prints: dict[str, str] = {}
    for name in ("cut.py", "timeline.py", "transcribe.py", "scenes.py", "shots.py",
                 "triage.py", "scene_describe.py", "quote_scout.py", "pool_build.py", "arrange.py",
                 "text_match.py", "llm_clients.py", "quality_zones.py", "refine.py",
                 "inspect_cut.py", "enriched_arrangement.py",
                 "render_remotion.py", "pipeline.py", "open_in_reigh.py"):
        path = tools_dir / name
        if path.is_file():
            prints[name] = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
    return prints


def _ref_path_for_metadata(ref: Path | None, out_dir: Path) -> str | None:
    # Store refs relative to out_dir when the file lives inside it, so the
    # metadata moves with the run directory. Fall back to absolute otherwise.
    if ref is None:
        return None
    resolved_ref = ref.resolve()
    resolved_out = out_dir.resolve()
    try:
        return str(resolved_ref.relative_to(resolved_out))
    except ValueError:
        return str(resolved_ref)


def _quality_zones_ref_from_args(args: argparse.Namespace) -> Path | None:
    for ref in (getattr(args, "scenes", None), getattr(args, "transcript", None)):
        if ref is None:
            continue
        candidate = ref.resolve().parent / "quality_zones.json"
        if candidate.is_file():
            return candidate
    return None


def _sha256_for_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clip_bounds_for_duration(entry: dict[str, Any], duration: float, *, start: float | None = None) -> dict[str, float]:
    start_sec = float(entry["src_start"] if start is None else start)
    source_end = float(entry["src_end"])
    if start_sec < 0 or source_end < start_sec:
        raise ValueError(
            f"Invalid source bounds for pool entry {entry.get('id')!r}: "
            f"{start_sec:.3f}-{source_end:.3f}"
        )
    source_duration = max(0.0, source_end - start_sec)
    visible_duration = min(source_duration, duration)
    bounds = {"from_": start_sec, "to": start_sec + visible_duration}
    hold = max(0.0, duration - source_duration)
    if hold > 0:
        bounds["hold"] = hold
    return bounds


_TEXT_STYLE_FONT = "Inter, system-ui, sans-serif"


def _text_style_preset_to_attrs(preset: Any) -> dict[str, Any]:
    if not isinstance(preset, str):
        return {}
    normalized = preset.lower().replace("_", "-")
    if "title" in normalized or "bold" in normalized:
        return {"fontFamily": _TEXT_STYLE_FONT, "fontSize": 64, "color": "#ffffff", "bold": True, "align": "center"}
    if "caption" in normalized:
        return {"fontFamily": _TEXT_STYLE_FONT, "fontSize": 36, "color": "#ffffff", "italic": "italic" in normalized, "align": "center"}
    if "closer" in normalized or "closing" in normalized:
        return {"fontFamily": _TEXT_STYLE_FONT, "fontSize": 48, "color": "#ffffff", "italic": True, "align": "center"}
    return {"fontFamily": _TEXT_STYLE_FONT, "fontSize": 36, "color": "#ffffff", "align": "center"}


def build_multitrack_timeline(
    arrangement: dict[str, Any],
    pool: dict[str, Any],
    registry: AssetRegistry,
    primary_asset: str | None,
    compiled_plan: list[dict[str, Any]] | None = None,
    theme: dict[str, Any] | None = None,
    theme_dir: Path | None = None,
    theme_slug: str | None = None,
) -> TimelineConfig:
    clips: list[dict[str, Any]] = []
    if primary_asset is None and "rant" in registry["assets"]:
        clips.append(
            {
                "id": "clip_a_rant",
                "at": 0,
                "track": "a1",
                "clipType": "media",
                "asset": "rant",
                "from": 0,
                "to": float(registry["assets"]["rant"]["duration"]),
            }
        )
    for plan in compiled_plan or compile_arrangement_plan(arrangement, pool):
        order = plan["order"]
        at = plan["at"]
        duration = plan["duration"]
        audio_entry = plan["audio_entry"]
        overlay_entry = plan["overlay_entry"]
        if audio_entry is not None:
            clips.append(
                {
                    "id": f"clip_a_{order}",
                    "source_uuid": plan["uuid"],
                    "at": at,
                    "track": "a1",
                    "clipType": "media",
                    "asset": audio_entry["asset"],
                    **_clip_bounds_for_duration(audio_entry, duration, start=plan["audio_trim_start"]),
                }
            )
            # v1 shows the speaker — the audio source at the same timestamp.
            clips.append(
                {
                    "id": f"clip_v1_{order}",
                    "source_uuid": plan["uuid"],
                    "at": at,
                    "track": "v1",
                    "clipType": "media",
                    "asset": audio_entry["asset"],
                    "volume": 0.0,
                    **_clip_bounds_for_duration(audio_entry, duration, start=plan["audio_trim_start"]),
                }
            )
        if overlay_entry is not None:
            if overlay_entry.get("kind") == "generative":
                # extends prior plan Step 12
                # INERT until prior Steps 7+10+12 land — validate_pool currently rejects kind == 'generative'
                params = dict(overlay_entry.get("defaults", {}))
                if isinstance(plan.get("visual_params"), dict):
                    params.update(plan["visual_params"])
                effect_id = overlay_entry["effect_id"]
                # Brand-controlled effects own their entrance/exit choice via
                # themes/<theme>/effects/<id>/defaults.json. Drop any animation
                # arrays the LLM put in the brief — content lives in params, styling
                # lives in the effect.
                params = _drop_brand_animation_overrides(effect_id, params)
                # Fallback precedence: explicit plan duration -> theme pacing default -> legacy 4s default.
                generation_duration = float(plan.get("duration") or _theme_default_clip_sec(theme) or _LEGACY_DEFAULT_CLIP_SEC)
                # Pure-generative clips have no source media; omit source_uuid and
                # hoist orchestration metadata to the clip top level. The theme is
                # referenced once at top level (timeline.theme); leave per-clip
                # generation absent unless something actually diverges per clip.
                clips.append(
                    {
                        "id": f"clip_g_{order}",
                        "at": at,
                        "track": "v1" if plan.get("role") == "primary" else "v2",
                        "clipType": effect_id,
                        "hold": generation_duration,
                        "pool_id": overlay_entry.get("id"),
                        "clip_order": plan.get("order"),
                        "params": params,
                    }
                )
                continue
            overlay_play_duration = plan.get("overlay_play_duration") or duration
            clips.append(
                {
                    "id": f"clip_v2_{order}",
                    "source_uuid": plan["uuid"],
                    "at": at,
                    "track": "v2",
                    "clipType": "media",
                    "asset": overlay_entry["asset"],
                    "volume": 0.0,
                    **_clip_bounds_for_duration(overlay_entry, overlay_play_duration),
                }
            )
        text_overlay = plan["text_overlay"]
        if isinstance(text_overlay, dict) and isinstance(text_overlay.get("content"), str):
            text_data: dict[str, Any] = {"content": text_overlay["content"]}
            text_data.update(_text_style_preset_to_attrs(text_overlay.get("style_preset")))
            clips.append(
                {
                    "id": f"clip_t_{order}",
                    "source_uuid": plan["uuid"],
                    "at": at,
                    "track": "v2",
                    "clipType": "text",
                    "hold": duration,
                    "x": 0,
                    "y": 0,
                    "width": 640,
                    "height": 160,
                    "text": text_data,
                }
            )
    if not theme_slug:
        raise SystemExit(
            "build_multitrack_timeline requires a theme_slug — pass --theme so the timeline can reference it."
        )
    # If the source's resolution/fps doesn't match the theme canvas, surface that
    # via theme_overrides.visual.canvas so the renderer knows what to do. We only
    # write an override if it actually diverges from the theme.
    theme_overrides: dict[str, Any] = {}
    if (
        primary_asset is not None
        and primary_asset in registry["assets"]
        and theme is not None
    ):
        canvas = theme.get("visual", {}).get("canvas") or {}
        primary = registry["assets"][primary_asset]
        primary_resolution = primary.get("resolution")
        primary_fps = primary.get("fps")
        theme_resolution = (
            f"{int(canvas['width'])}x{int(canvas['height'])}"
            if isinstance(canvas.get("width"), (int, float)) and isinstance(canvas.get("height"), (int, float))
            else None
        )
        theme_fps = canvas.get("fps") if isinstance(canvas.get("fps"), (int, float)) else None
        canvas_override: dict[str, Any] = {}
        if primary_resolution and primary_resolution != theme_resolution:
            try:
                width_str, height_str = primary_resolution.split("x", 1)
                canvas_override["width"] = int(width_str)
                canvas_override["height"] = int(height_str)
            except ValueError:
                pass
        if primary_fps is not None and (theme_fps is None or float(primary_fps) != float(theme_fps)):
            canvas_override["fps"] = primary_fps
        if canvas_override:
            theme_overrides["visual"] = {"canvas": canvas_override}
    track_ids = {str(clip.get("track")) for clip in clips if clip.get("track")}
    if "a1" in track_ids:
        tracks = [
            {"id": "v1", "kind": "visual", "label": "Speaker"},
            {"id": "v2", "kind": "visual", "label": "B-roll"},
            {"id": "a1", "kind": "audio", "label": "Dialogue"},
        ]
    else:
        tracks = [{"id": "v1", "kind": "visual", "label": "Speaker"}] if "v1" in track_ids or not clips else []
        if "v2" in track_ids:
            tracks.append({"id": "v2", "kind": "visual", "label": "B-roll"})
        if "a1" in track_ids:
            tracks.append({"id": "a1", "kind": "audio", "label": "Dialogue"})
    config: dict[str, Any] = {
        "theme": theme_slug,
        "tracks": tracks,
        "clips": clips,
    }
    if theme_overrides:
        config["theme_overrides"] = theme_overrides
    # SD-009: every emitted timeline carries the canonical `output` block so
    # downstream consumers (Reigh's renderer, the publish CLI, etc.) get
    # resolution/fps/file without re-resolving the theme. Sourced from
    # theme.visual.canvas via materialize_output() in the shared schema package;
    # background/background_scale pass through from any prior timeline.output.
    if theme is not None:
        merged_theme = _merged_theme_for_output(theme, theme_overrides)
        config["output"] = materialize_output(config, merged_theme)
    return config


def _merged_theme_for_output(theme: dict[str, Any], theme_overrides: dict[str, Any]) -> dict[str, Any]:
    """Apply theme_overrides.visual onto the loaded theme so materialize_output()
    sees the canvas the renderer will actually use (e.g. when the source asset's
    resolution/fps diverges from the brand canvas).
    """
    if not theme_overrides:
        return theme
    visual_override = theme_overrides.get("visual")
    if not isinstance(visual_override, dict):
        return theme
    merged = dict(theme)
    base_visual = dict(theme.get("visual") or {})
    canvas = dict(base_visual.get("canvas") or {})
    canvas_override = visual_override.get("canvas")
    if isinstance(canvas_override, dict):
        canvas.update(canvas_override)
    base_visual["canvas"] = canvas
    merged["visual"] = base_visual
    return merged


def _joined_segment_text(segment_ids: list[int], transcript: list[dict[str, Any]] | None) -> str | None:
    if transcript is None:
        return None
    parts = [
        str(transcript[index].get("text", "")).strip()
        for index in segment_ids
        if 0 <= index < len(transcript)
    ]
    joined = " ".join(part for part in parts if part).strip()
    return joined or None


def _pool_entry_caption_kind(entry: dict[str, Any]) -> str:
    return "dialogue" if entry.get("category") == "dialogue" else "visual"


def build_metadata_from_arrangement(
    arrangement: dict[str, Any],
    pool: dict[str, Any],
    registry: AssetRegistry,
    sources_meta: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    primary_asset: str,
    transcript: list[dict[str, Any]] | None,
    *,
    quality_zones_ref: Path | None = None,
    pool_sha256: str,
    arrangement_sha256: str,
    brief_sha256: str,
    compiled_plan: list[dict[str, Any]] | None = None,
) -> PipelineMetadata:
    _ = registry
    clips: dict[str, dict[str, Any]] = {}
    for plan in compiled_plan or compile_arrangement_plan(arrangement, pool):
        order = plan["order"]
        audio_entry = plan["audio_entry"]
        overlay_entry = plan["overlay_entry"]
        rationale = plan["rationale"]
        if audio_entry is not None:
            audio_meta: dict[str, Any] = {
                "source_uuid": plan["uuid"],
                "pool_id": audio_entry["id"],
                "pool_kind": audio_entry["category"],
                "source_ids": dict(audio_entry.get("source_ids", {})),
                "arrangement_notes": rationale,
                "caption_kind": _pool_entry_caption_kind(audio_entry),
                "source_transcript_text": None,
            }
            if audio_entry.get("category") == "dialogue":
                segment_ids = audio_entry.get("source_ids", {}).get("segment_ids", [])
                if isinstance(segment_ids, list):
                    audio_meta["source_transcript_text"] = _joined_segment_text(segment_ids, transcript)
            clips[f"clip_a_{order}"] = audio_meta
            clips[f"clip_v1_{order}"] = {
                "source_uuid": plan["uuid"],
                "pool_id": audio_entry["id"],
                "pool_kind": audio_entry["category"],
                "source_ids": dict(audio_entry.get("source_ids", {})),
                "arrangement_notes": rationale,
                "caption_kind": "visual",
                "source_transcript_text": None,
            }

        if overlay_entry is not None:
            if overlay_entry.get("kind") == "generative":
                clips[f"clip_g_{order}"] = {
                    "source_uuid": plan["uuid"],
                    "pool_id": overlay_entry["id"],
                    "pool_kind": "visual",
                    "arrangement_notes": rationale,
                    "caption_kind": "visual",
                    "source_transcript_text": None,
                }
                continue
            clips[f"clip_v2_{order}"] = {
                "source_uuid": plan["uuid"],
                "pool_id": overlay_entry["id"],
                "pool_kind": overlay_entry["category"],
                "source_ids": dict(overlay_entry.get("source_ids", {})),
                "arrangement_notes": rationale,
                "caption_kind": "visual",
                "source_transcript_text": None,
            }
        text_overlay = plan["text_overlay"]
        if isinstance(text_overlay, dict) and isinstance(text_overlay.get("content"), str):
            clips[f"clip_t_{order}"] = {
                "source_uuid": plan["uuid"],
                "pool_id": None,
                "pool_kind": "text",
                "arrangement_notes": rationale,
                "caption_kind": "visual",
                "source_transcript_text": None,
                "text_overlay_content": text_overlay["content"],
            }

    out_dir = args.out.resolve()
    sources = {key: dict(value) for key, value in sources_meta.items()}
    if primary_asset is not None:
        primary_source = dict(sources.get(primary_asset, {}))
        primary_entry = registry["assets"].get(primary_asset, {})
        if isinstance(primary_entry.get("url"), str):
            primary_source["url"] = primary_entry["url"]
        primary_source["scenes_ref"] = _ref_path_for_metadata(args.scenes, out_dir)
        if args.transcript is not None:
            primary_source["transcript_ref"] = _ref_path_for_metadata(args.transcript, out_dir)
        if quality_zones_ref is not None:
            primary_source["quality_zones_ref"] = _ref_path_for_metadata(quality_zones_ref, out_dir)
        if args.shots is not None:
            primary_source["shots_ref"] = _ref_path_for_metadata(args.shots, out_dir)
        sources[primary_asset] = primary_source
    steps_run = ["cut"]
    if args.transcript is not None:
        steps_run.insert(0, "transcribe")
    if args.scenes is not None:
        steps_run.insert(-1, "scenes")
    if quality_zones_ref is not None:
        steps_run.insert(-1, "quality_zones")
    if args.shots is not None:
        steps_run.insert(-1, "shots")
    if args.arrangement is not None:
        steps_run.insert(-1, "arrange")
    return {
        "version": METADATA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "pipeline": {
            "steps_run": steps_run,
            "tool_versions": _tool_fingerprints(PACKAGE_ROOT),
            "config_snapshot": {
                "primary_asset": primary_asset,
                "renderer": args.renderer,
                "mode": "arrangement",
            },
            "pool_provenance": {
                "pool_sha256": pool_sha256,
                "arrangement_sha256": arrangement_sha256,
                "brief_sha256": brief_sha256,
                "source_slug": arrangement.get("source_slug"),
                "brief_slug": arrangement.get("brief_slug"),
            },
        },
        "clips": clips,
        "sources": sources,
    }


def arrangement_edl_rows(
    arrangement: dict[str, Any],
    pool: dict[str, Any],
    transcript: list[dict[str, Any]] | None,
    compiled_plan: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for plan in compiled_plan or compile_arrangement_plan(arrangement, pool):
        source_entry = plan["audio_entry"] or plan["overlay_entry"]
        if source_entry is None or source_entry.get("kind") == "generative":
            continue
        source_ids = source_entry.get("source_ids", {})
        caption = None
        if source_entry.get("category") == "dialogue" and isinstance(source_ids, dict):
            segment_ids = source_ids.get("segment_ids")
            if isinstance(segment_ids, list):
                caption = _joined_segment_text(segment_ids, transcript)
        if caption is None:
            caption = (
                source_entry.get("text")
                or source_entry.get("subject")
                or source_entry.get("event_label")
                or ""
            )
        rows.append(
            {
                "asset": source_entry["asset"],
                "start": float(plan["audio_trim_start"]) if plan["audio_entry"] is not None else float(source_entry["src_start"]),
                "end": (
                    float(plan["audio_trim_start"]) + float(plan["duration"])
                    if plan["audio_entry"] is not None
                    else float(source_entry["src_start"]) + float(plan["duration"])
                ),
                "caption": caption,
            }
        )
    return rows

def write_edl(
    selected: list[dict[str, Any]],
    out_dir: Path,
    asset_paths: dict[str, Path],
    asset_urls: dict[str, str],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    edl_path = out_dir / "hype.edl.csv"
    with edl_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["order", "src_start", "src_end", "src_path", "caption"])
        for order, item in enumerate(selected, start=1):
            asset_key = item["asset"]
            src_path = asset_urls.get(asset_key) or str(asset_paths[asset_key].resolve())
            writer.writerow(
                [
                    order,
                    f"{float(item['start']):.3f}",
                    f"{float(item['end']):.3f}",
                    src_path,
                    item["caption"],
                ]
            )
    return edl_path


def _register_cut_outputs(
    *,
    out_dir: Path,
    stage: str,
    parents: list[str] | None = None,
    rendered_path: Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    audit = AuditContext.from_env()
    if audit is None:
        return
    parent_ids = list(parents or [])
    outputs = []
    for kind, filename, label in (
        ("edl", "hype.edl.csv", "Edit decision list"),
        ("timeline", "hype.timeline.json", "Timeline"),
        ("assets_registry", "hype.assets.json", "Asset registry"),
        ("metadata", "hype.metadata.json", "Pipeline metadata"),
    ):
        path = out_dir / filename
        if path.exists():
            outputs.append(audit.register_asset(kind=kind, path=path, label=label, parents=parent_ids, stage=stage, metadata=metadata))
    if rendered_path is not None and rendered_path.exists():
        outputs.append(audit.register_asset(kind="render", path=rendered_path, label="Rendered hype video", parents=outputs, stage=stage, metadata=metadata))
    audit.register_node(stage=stage, label="Build cut artifacts", parents=parent_ids, outputs=outputs, metadata=metadata or {})

def ensure_resume_mode_args(args: argparse.Namespace) -> None:
    conflicts: list[tuple[str, Any]] = [
        ("--scenes", args.scenes),
        ("--video", args.video),
        ("--shots", args.shots),
        ("--transcript", args.transcript),
        ("--primary-asset", args.primary_asset),
        ("--asset", args.asset),
    ]
    for flag, value in conflicts:
        if value not in (None, []):
            raise SystemExit(f"--timeline cannot be combined with {flag}")

def rebase_registry_paths(registry: AssetRegistry, assets_dir: Path) -> AssetRegistry:
    rebased_assets: dict[str, dict[str, Any]] = {}
    for key, entry in registry["assets"].items():
        rebased_entry = dict(entry)
        file_value = rebased_entry.get("file")
        if isinstance(file_value, str):
            resolved = Path(file_value)
            if not resolved.is_absolute():
                rebased_entry["file"] = str((assets_dir / file_value).resolve())
        rebased_assets[key] = rebased_entry
    return {"assets": rebased_assets}

def build_resume_metadata(
    config: TimelineConfig,
    prior_meta: PipelineMetadata | None,
    *,
    render: bool,
    renderer: str,
) -> PipelineMetadata:
    clip_ids = [clip["id"] for clip in config["clips"]]
    prior_clips = prior_meta.get("clips", {}) if isinstance(prior_meta, dict) else {}
    clips: dict[str, dict[str, Any]] = {}
    if isinstance(prior_clips, dict):
        for clip_id in clip_ids:
            clip_meta = prior_clips.get(clip_id)
            if isinstance(clip_meta, dict):
                clips[clip_id] = dict(clip_meta)
    prior_sources = prior_meta.get("sources", {}) if isinstance(prior_meta, dict) else {}
    sources = {key: dict(value) for key, value in prior_sources.items()} if isinstance(prior_sources, dict) else {}
    return {
        "version": METADATA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "pipeline": {
            "steps_run": ["cut"],
            "tool_versions": {"cut.py": "sprint3"},
            "config_snapshot": {
                "mode": "timeline_resume",
                "render": render,
                "renderer": renderer,
            },
        },
        "clips": clips,
        "sources": sources,
    }

def run_resume_mode(args: argparse.Namespace) -> int:
    ensure_resume_mode_args(args)

    timeline_path = args.timeline.resolve()
    if not timeline_path.is_file():
        raise SystemExit(f"Timeline file not found: {timeline_path}")
    source_dir = timeline_path.parent
    assets_path_in = args.assets.resolve() if args.assets is not None else source_dir / "hype.assets.json"
    if not assets_path_in.is_file():
        raise SystemExit(f"Assets file not found: {assets_path_in}")

    config = load_timeline(timeline_path)
    registry = load_registry(assets_path_in)

    # SD-009: backfill the canonical `output` block if the resumed timeline
    # was authored before materialize_output() was wired in. Resolves the
    # timeline's theme slug + theme_overrides via the workspace themes root.
    if "output" not in config:
        themes_root = WORKSPACE_ROOT / "themes"
        try:
            from .timeline import resolve_timeline_theme
            merged_theme = resolve_timeline_theme(config, themes_root)
            config["output"] = materialize_output(config, merged_theme)
        except (FileNotFoundError, ValueError):
            # Theme not installed in this checkout; leave output absent rather
            # than fail the resume — the publish path will refuse on its own
            # validate gate if downstream needs the block.
            pass

    missing_assets = sorted(
        {
            asset
            for clip in config["clips"]
            for asset in [clip.get("asset")]
            if asset is not None and asset not in registry["assets"]
        }
    )
    if missing_assets:
        quoted = ", ".join(repr(asset) for asset in missing_assets)
        raise SystemExit(f"Timeline references assets missing from registry: {quoted}")

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    timeline_path_out = out_dir / "hype.timeline.json"
    assets_path_out = out_dir / "hype.assets.json"
    metadata_path_out = out_dir / "hype.metadata.json"
    save_timeline(config, timeline_path_out)
    if out_dir == assets_path_in.parent.resolve():
        save_registry(registry, assets_path_out)
    else:
        save_registry(rebase_registry_paths(registry, assets_path_in.parent), assets_path_out)

    prior_meta_path = source_dir / "hype.metadata.json"
    prior_meta = load_metadata(prior_meta_path) if prior_meta_path.exists() else None
    save_metadata(
        build_resume_metadata(config, prior_meta, render=bool(args.render), renderer=args.renderer),
        metadata_path_out,
    )

    summary = f"timeline={timeline_path_out} assets={assets_path_out} metadata={metadata_path_out}"
    if args.render:
        from .render_remotion import render as render_remotion

        hype_path = render_remotion(
            timeline_path_out,
            assets_path_out,
            out_dir / "hype.mp4",
            project_dir=REPO_ROOT / "remotion",
        )
        summary = f"{summary} hype={hype_path}"
    _register_cut_outputs(
        out_dir=out_dir,
        stage="cut.resume",
        metadata={"mode": "timeline_resume", "render": bool(args.render), "renderer": args.renderer},
        rendered_path=out_dir / "hype.mp4" if args.render else None,
    )
    print(f"wrote {summary}")
    return 0

def main(argv: Sequence[str] | None = None) -> int:
    global _FFPROBE_VERBOSE

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeline is not None:
        return run_resume_mode(args)
    theme_path = _resolve_theme_path(args.theme)
    theme = load_theme(theme_path) if theme_path is not None else None
    theme_dir = theme_root(theme_path).resolve() if theme_path is not None else None
    theme_slug = _theme_slug_from_path(theme_path)
    pure_generative = args.video is None and args.audio is not None
    no_audio = args.video is None and args.audio is None
    if args.scenes is None and not (pure_generative or no_audio):
        raise SystemExit("--scenes is required unless --timeline is provided")
    if args.arrangement is None:
        raise SystemExit("--arrangement is required unless --timeline is provided")
    if args.pool is None:
        raise SystemExit("--pool is required unless --timeline is provided")
    if args.brief is None:
        raise SystemExit("--brief is required unless --timeline is provided")
    if args.transcript is None and not no_audio:
        raise SystemExit("--transcript is required unless --timeline is provided")
    _FFPROBE_VERBOSE = bool(args.verbose)

    scenes_path = args.scenes.resolve() if args.scenes is not None else None
    out_dir = args.out.resolve()
    if scenes_path is not None and not scenes_path.is_file():
        raise SystemExit(f"Scenes file not found: {scenes_path}")
    if args.video is not None and not asset_cache.is_url(args.video) and not Path(args.video).resolve().is_file():
        raise SystemExit(f"Video file not found: {Path(args.video).resolve()}")
    if args.transcript is not None and not args.transcript.resolve().is_file():
        raise SystemExit(f"Transcript file not found: {args.transcript.resolve()}")
    if args.shots is not None and not args.shots.resolve().is_file():
        raise SystemExit(f"Shots file not found: {args.shots.resolve()}")
    if not args.arrangement.resolve().is_file():
        raise SystemExit(f"Arrangement file not found: {args.arrangement.resolve()}")
    if not args.pool.resolve().is_file():
        raise SystemExit(f"Pool file not found: {args.pool.resolve()}")
    if not args.brief.resolve().is_file():
        raise SystemExit(f"Brief file not found: {args.brief.resolve()}")
    if scenes_path is not None:
        load_scenes(scenes_path)
    transcript = None if no_audio else load_transcript_segments(args.transcript.resolve())
    if args.shots is not None:
        load_json(args.shots.resolve())

    asset_paths, asset_urls = resolve_asset_paths(args)
    for key, path in asset_paths.items():
        if not path.is_file():
            raise SystemExit(f"Asset file not found for {key!r}: {path}")
    asset_keys = set(asset_paths) | set(asset_urls)

    assets_path = out_dir / "hype.assets.json"
    if assets_path.exists():
        existing_registry = load_registry(assets_path)
    else:
        existing_registry = {"assets": {}}

    if args.primary_asset is None:
        if "main" in asset_keys:
            primary_asset = "main"
        elif pure_generative and "rant" in asset_keys:
            primary_asset = None
        elif no_audio:
            primary_asset = None
        else:
            raise SystemExit(
                "--primary-asset is required when --video is not provided as the main asset. "
                f"Available keys: {sorted(asset_keys)}"
            )
    else:
        if args.primary_asset not in asset_keys:
            raise SystemExit(
                f"--primary-asset={args.primary_asset!r} is not one of the configured asset keys: "
                f"{sorted(asset_keys)}"
            )
        primary_asset = args.primary_asset

    metadata_path = out_dir / "hype.metadata.json"
    prior_meta = load_metadata(metadata_path) if metadata_path.exists() else None
    registry, sources_meta = build_registry(asset_paths, asset_urls, existing_registry, prior_meta)

    arrangement_path = args.arrangement.resolve()
    pool_path = args.pool.resolve()
    brief_path = args.brief.resolve()
    pool_sha256 = _sha256_for_path(pool_path)
    arrangement_sha256 = _sha256_for_path(arrangement_path)
    brief_sha256 = _sha256_for_path(brief_path)
    pool = load_pool(pool_path)
    pool_ids = {entry["id"] for entry in pool["entries"]}
    arrangement = load_arrangement(arrangement_path, pool_ids, assign_missing_uuids=True)
    if args.video is not None and arrangement_uses_generative_visuals(arrangement, pool):
        raise SystemExit("Source-cut mode cannot materialize generative visual_source entries; rerun arrange without --allow-generative-effects.")
    if not is_all_generative_arrangement(arrangement, pool):
        validate_arrangement_duration_window(arrangement)
    compiled_plan = compile_arrangement_plan(arrangement, pool)
    edl_rows = arrangement_edl_rows(arrangement, pool, transcript, compiled_plan=compiled_plan)
    if theme_slug is None:
        # Timelines now reference a theme by slug at top level. Default to the
        # banodoco-default theme when --theme isn't supplied so the timeline still
        # validates; callers needing a specific brand pass --theme.
        theme_slug = "banodoco-default"
    timeline = build_multitrack_timeline(
        arrangement,
        pool,
        registry,
        primary_asset,
        compiled_plan=compiled_plan,
        theme=theme,
        theme_dir=theme_dir,
        theme_slug=theme_slug,
    )
    meta = build_metadata_from_arrangement(
        arrangement,
        pool,
        registry,
        sources_meta,
        args,
        primary_asset,
        transcript,
        quality_zones_ref=_quality_zones_ref_from_args(args),
        pool_sha256=pool_sha256,
        arrangement_sha256=arrangement_sha256,
        brief_sha256=brief_sha256,
        compiled_plan=compiled_plan,
    )
    edl_path = write_edl(edl_rows, out_dir, asset_paths, asset_urls)
    timeline_path = out_dir / "hype.timeline.json"
    save_timeline(timeline, timeline_path)
    save_registry(registry, assets_path)
    save_metadata(meta, metadata_path)
    rendered_path = None
    if args.render:
        from .render_remotion import render as render_remotion

        hype_path = render_remotion(
            timeline_path,
            assets_path,
            out_dir / "hype.mp4",
            project_dir=REPO_ROOT / "remotion",
        )
        rendered_path = hype_path
        print(
            f"wrote_edl={edl_path} timeline={timeline_path} assets={assets_path} metadata={metadata_path} "
            f"hype={hype_path}"
        )
    else:
        print(f"wrote_edl={edl_path} timeline={timeline_path} assets={assets_path} metadata={metadata_path}")
    _register_cut_outputs(
        out_dir=out_dir,
        stage="cut",
        metadata={"clips": len(timeline.get("clips", [])), "render": bool(args.render), "renderer": args.renderer},
        rendered_path=rendered_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
