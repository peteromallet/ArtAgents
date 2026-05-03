#!/usr/bin/env python3
"""Assemble prepared iteration data into render-compatible adapter files."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from artagents._paths import REPO_ROOT
from artagents import modalities, timeline
from artagents.threads.schema import SCHEMA_VERSION

QUALITY_FLOOR = 0.6
DEFAULT_CLIP_SECONDS = 4.0


class AssembleError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assemble iteration.prepare outputs into render adapter files.")
    parser.add_argument("--prepare-dir", required=True, help="Directory containing iteration.prepare outputs.")
    parser.add_argument("--out", required=True, help="Directory for iteration.assemble outputs.")
    parser.add_argument("--force", action="store_true", help="Bypass the data_quality floor and record forced=true.")
    parser.add_argument("--direction", default=None, help="Optional direction label. It is not parsed in v1.")
    parser.add_argument("--mode", default="chaptered", help="Only chaptered is supported in v1.")
    parser.add_argument("--theme", default=None, help="Optional theme slug/path for style precedence.")
    parser.add_argument("--style-preset", default=None, help="Optional style preset label.")
    parser.add_argument("--audio-bed", default="auto", help="auto, iterations-as-bed, theme-declared-bed, or silence-room-tone.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Repository root for resolving artifact paths.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = assemble_iteration(
            prepare_dir=Path(args.prepare_dir),
            out_path=Path(args.out),
            repo_root=Path(args.repo_root),
            force=bool(args.force),
            direction=args.direction,
            mode=args.mode,
            theme=args.theme,
            style_preset=args.style_preset,
            audio_bed=args.audio_bed,
        )
    except AssembleError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for diagnostic in result["diagnostics"]:
        print(diagnostic)
    print(json.dumps({"timeline": result["timeline_path"], "manifest": result["manifest_path"]}, sort_keys=True))
    return 0


def assemble_iteration(
    *,
    prepare_dir: Path,
    out_path: Path,
    repo_root: Path = REPO_ROOT,
    force: bool = False,
    direction: str | None = None,
    mode: str = "chaptered",
    theme: str | None = None,
    style_preset: str | None = None,
    audio_bed: str = "auto",
) -> dict[str, Any]:
    if mode != "chaptered":
        raise AssembleError("iteration.assemble supports only --mode chaptered in v1; parallel and interleaved are deferred.")
    if audio_bed == "generated_music":
        raise AssembleError("iteration.assemble never generates music; use auto, iterations-as-bed, theme-declared-bed, or silence-room-tone.")
    prepare_dir = prepare_dir.expanduser().resolve()
    out_path = out_path.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    prepare_manifest = _read_json(prepare_dir / "iteration.manifest.json")
    quality = _read_json(prepare_dir / "iteration.quality.json")
    _enforce_quality_floor(quality, force=force)

    assembly = build_assembly(
        prepare_manifest,
        quality,
        repo_root=repo_root,
        force=force,
        direction=direction,
        mode=mode,
        theme=theme,
        style_preset=style_preset,
        audio_bed=audio_bed,
    )
    out_path.mkdir(parents=True, exist_ok=True)
    timeline_path = out_path / "iteration.timeline.json"
    hype_timeline_path = out_path / "hype.timeline.json"
    manifest_path = out_path / "iteration.manifest.json"
    quality_path = out_path / "iteration.quality.json"
    report_path = out_path / "iteration.report.html"
    assets_path = out_path / "hype.assets.json"

    timeline.save_timeline(assembly["timeline"], timeline_path)
    timeline.save_timeline(assembly["timeline"], hype_timeline_path)
    timeline.save_registry(assembly["assets"], assets_path)
    _write_json(manifest_path, assembly["manifest"])
    _write_json(quality_path, assembly["quality"])
    report_path.write_text(assembly["report_html"], encoding="utf-8")
    return {
        "timeline_path": str(timeline_path),
        "manifest_path": str(manifest_path),
        "quality_path": str(quality_path),
        "report_path": str(report_path),
        "hype_timeline_path": str(hype_timeline_path),
        "hype_assets_path": str(assets_path),
        "diagnostics": assembly["diagnostics"],
    }


def build_assembly(
    prepare_manifest: Mapping[str, Any],
    quality: Mapping[str, Any],
    *,
    repo_root: Path,
    force: bool,
    direction: str | None,
    mode: str,
    theme: str | None,
    style_preset: str | None,
    audio_bed: str,
) -> dict[str, Any]:
    clips: list[dict[str, Any]] = []
    assets: dict[str, dict[str, Any]] = {}
    decisions: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    current_at = 0.0
    total_duration = 0.0
    audio_duration = 0.0

    for run_index, run in enumerate(prepare_manifest.get("runs", []) or []):
        if not isinstance(run, Mapping):
            continue
        for artifact_index, artifact in enumerate(run.get("output_artifacts", []) or []):
            if not isinstance(artifact, Mapping):
                continue
            duration = float(artifact.get("duration") or DEFAULT_CLIP_SECONDS)
            resolution = modalities.resolve_artifact(dict(artifact))
            renderer_id = str(resolution["renderer"])
            renderer_info = modalities.inspect_renderer(renderer_id)
            asset_id = f"asset_{run.get('run_id')}_{artifact_index}"
            clip = _clip_for_artifact(
                artifact,
                resolution=resolution,
                asset_id=asset_id,
                run_id=str(run.get("run_id")),
                at=current_at,
                duration=duration,
            )
            clips.append(clip)
            if artifact.get("path"):
                assets[asset_id] = _asset_entry(artifact, repo_root=repo_root, duration=duration)
            if renderer_info.get("produces_audio"):
                audio_duration += duration
            total_duration += duration
            current_at += duration
            decision = {
                "run_id": run.get("run_id"),
                "artifact_index": artifact_index,
                "kind": artifact.get("kind"),
                "renderer": renderer_id,
                "clip_mode": resolution.get("clip_mode"),
                "fallback": bool(resolution.get("fallback", False)),
            }
            if resolution.get("fallback"):
                diagnostic = f"renderer-fallback: {resolution['diagnostic']}"
                diagnostic_html = resolution.get("html_aside")
                decision["diagnostic"] = resolution["diagnostic"]
                decision["html_aside"] = diagnostic_html
                diagnostics.append(diagnostic)
            decisions.append(decision)

    selected_audio_bed = _select_audio_bed(audio_bed, audio_duration=audio_duration, total_duration=total_duration, theme=theme)
    timeline_payload = {
        "theme": theme or "banodoco-default",
        "tracks": [
            {"id": "v1", "kind": "visual", "label": "Iteration"},
            {"id": "a1", "kind": "audio", "label": "Audio bed"},
        ],
        "clips": clips,
        "iteration": {
            "schema_version": SCHEMA_VERSION,
            "mode": mode,
            "direction_label": direction,
            "style_source": _style_source(theme=theme, direction=direction, style_preset=style_preset),
            "audio_bed": selected_audio_bed,
        },
    }
    assembled_quality = dict(quality)
    assembled_quality["forced"] = bool(force)
    final_manifest = dict(prepare_manifest)
    final_manifest["assembly"] = {
        "schema_version": SCHEMA_VERSION,
        "forced": bool(force),
        "mode": mode,
        "direction_label": direction,
        "style_source": _style_source(theme=theme, direction=direction, style_preset=style_preset),
        "audio_bed": selected_audio_bed,
        "renderer_decisions": decisions,
        "fallback_diagnostics": diagnostics,
    }
    final_manifest["renderer_candidates"] = {str(item["kind"]): item for item in decisions if item.get("kind") is not None}
    return {
        "timeline": timeline_payload,
        "assets": {"assets": assets},
        "manifest": final_manifest,
        "quality": assembled_quality,
        "report_html": _report_html(final_manifest, quality, decisions),
        "diagnostics": diagnostics,
    }


def _enforce_quality_floor(quality: Mapping[str, Any], *, force: bool) -> None:
    data_quality = float(quality.get("data_quality") or 0.0)
    if data_quality >= QUALITY_FLOOR or force:
        return
    unresolved = quality.get("unresolved_producer_runs", []) or []
    commands = []
    for item in unresolved:
        if not isinstance(item, Mapping):
            continue
        run_id = item.get("run_id")
        if run_id:
            commands.append(f"python3 -m artagents thread backfill  # unresolved producer {run_id}")
    detail = "\n".join(commands) if commands else "python3 -m artagents thread backfill"
    raise AssembleError(f"data_quality {data_quality:.3f} is below {QUALITY_FLOOR:.1f}; run:\n{detail}\nUse --force to assemble anyway.")


def _clip_for_artifact(
    artifact: Mapping[str, Any],
    *,
    resolution: Mapping[str, Any],
    asset_id: str,
    run_id: str,
    at: float,
    duration: float,
) -> dict[str, Any]:
    kind = artifact.get("kind")
    renderer = resolution.get("renderer")
    base = {
        "id": f"iteration-{run_id}-{int(at * 1000)}",
        "at": at,
        "track": "a1" if kind == "audio" else "v1",
        "hold": duration,
        "params": {"renderer": renderer, "run_id": run_id, "kind": kind},
    }
    if resolution.get("fallback") or not artifact.get("path"):
        content = resolution.get("html_aside") or html.escape(str(artifact.get("label") or kind or "artifact"))
        return {
            **base,
            "clipType": "text-card",
            "params": {**base["params"], "content": content, "fallback": bool(resolution.get("fallback"))},
        }
    return {
        **base,
        "clipType": "media",
        "asset": asset_id,
    }


def _asset_entry(artifact: Mapping[str, Any], *, repo_root: Path, duration: float) -> dict[str, Any]:
    path = Path(str(artifact["path"]))
    file_path = path if path.is_absolute() else (repo_root / path).resolve()
    entry: dict[str, Any] = {
        "file": str(file_path),
        "type": str(artifact.get("kind") or "opaque"),
        "duration": duration,
    }
    if artifact.get("sha256"):
        entry["content_sha256"] = str(artifact["sha256"])
    return entry


def _select_audio_bed(audio_bed: str, *, audio_duration: float, total_duration: float, theme: str | None) -> str:
    if audio_bed and audio_bed != "auto":
        return audio_bed
    coverage = (audio_duration / total_duration) if total_duration else 0.0
    if coverage > 0.4:
        return "iterations-as-bed"
    if theme:
        return "theme-declared-bed"
    return "silence-room-tone"


def _style_source(*, theme: str | None, direction: str | None, style_preset: str | None) -> str:
    if theme:
        return "theme"
    if direction:
        return "direction-label"
    if style_preset:
        return "style-preset"
    return "defaults"


def _report_html(manifest: Mapping[str, Any], quality: Mapping[str, Any], decisions: list[dict[str, Any]]) -> str:
    fallback_asides = "\n".join(str(item.get("html_aside")) for item in decisions if item.get("html_aside"))
    return (
        "<!doctype html>\n"
        "<html><head><meta charset=\"utf-8\"><title>Iteration Report</title></head><body>\n"
        f"<h1>Iteration Report</h1><p>Quality: {quality.get('data_quality')}</p>\n"
        f"{fallback_asides}\n"
        "</body></html>\n"
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AssembleError(f"missing prepare output: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AssembleError(f"invalid JSON prepare output: {path}") from exc
    if not isinstance(data, dict):
        raise AssembleError(f"prepare output must be an object: {path}")
    return data


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
