#!/usr/bin/env python3
"""Plan and generate source-relevant thumbnail candidates for a video."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Sequence

from artagents.packs.builtin.asset_cache import run as asset_cache


DEFAULT_SIZE = "1536x864"
DEFAULT_COUNT = 1
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_QUALITY = "medium"
DEFAULT_OUTPUT_FORMAT = "png"
DEFAULT_VISUAL_MODE = "fast"
DEFAULT_REFERENCE_MODE = "auto"
DEFAULT_MAX_CANDIDATES = 20
MINIMAL_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300030202030202030303030403030405080505"
    "0404050a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812"
    "141514ffdb00430103040405040509050509140d0b0d14141414141414141414141414141414141414141414"
    "141414141414141414141414141414141414141414141414141414141414ffc0001108000100010301220002"
    "1101031101ffc4001400010000000000000000000000000000000000000008ffc40014100100000000000000"
    "000000000000000000000000ffda000c03010002110311003f00b2c001ffd9"
)

OUTPUT_DIRS = {
    "evidence": "evidence",
    "references": "references",
    "prompts": "prompts",
    "generated": "generated",
    "review": "review",
}

PERSON_TERMS = {
    "face",
    "headshot",
    "host",
    "interview",
    "man",
    "person",
    "portrait",
    "presenter",
    "speaker",
    "talking",
    "woman",
}
SCENE_TERMS = {
    "background",
    "crowd",
    "environment",
    "location",
    "room",
    "scene",
    "stage",
    "studio",
    "venue",
}
TEXT_TERMS = {
    "caption",
    "headline",
    "quote",
    "subtitle",
    "text",
    "title",
    "words",
}
EMOTION_TERMS = {
    "angry",
    "dramatic",
    "emotional",
    "excited",
    "funny",
    "intense",
    "laugh",
    "shocked",
    "surprised",
}


def _json_default(value: object) -> str:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def parse_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value.strip())
    if not match:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT, for example 1536x864")
    return int(match.group(1)), int(match.group(2))


def normalized_size(value: str) -> str:
    width, height = parse_size(value)
    return f"{width}x{height}"


def build_output_layout(out_dir: Path) -> dict[str, Path]:
    root = out_dir.expanduser().resolve()
    layout = {"root": root}
    layout.update({key: root / name for key, name in OUTPUT_DIRS.items()})
    return layout


def ensure_output_layout(layout: dict[str, Path]) -> None:
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)


def _query_tokens(query: str) -> list[str]:
    return sorted(set(re.findall(r"[a-z0-9]+", query.lower())))


def plan_evidence_needs(query: str) -> dict[str, Any]:
    """Return a deterministic source-search plan from the user thumbnail query."""
    tokens = _query_tokens(query)
    token_set = set(tokens)

    needs: list[dict[str, Any]] = []
    if token_set & PERSON_TERMS:
        needs.append(
            {
                "id": "speaker_or_person_framing",
                "reason": "Query appears to need a readable person or speaker-oriented frame.",
                "source": "video_frames",
                "selection_hint": "Prefer clear upper-body or face-visible composition when present.",
            }
        )
    if token_set & SCENE_TERMS:
        needs.append(
            {
                "id": "scene_context",
                "reason": "Query references the surrounding scene or location.",
                "source": "scene_frames",
                "selection_hint": "Prefer frames that show the environment clearly.",
            }
        )
    if token_set & TEXT_TERMS:
        needs.append(
            {
                "id": "title_or_quote_context",
                "reason": "Query references text, a title, caption, or quoted idea.",
                "source": "query_text",
                "selection_hint": "Preserve room for readable thumbnail text.",
            }
        )
    if token_set & EMOTION_TERMS:
        needs.append(
            {
                "id": "expressive_moment",
                "reason": "Query asks for an emotional or high-energy thumbnail.",
                "source": "video_frames",
                "selection_hint": "Prefer visually expressive frames.",
            }
        )
    if not needs:
        needs.append(
            {
                "id": "representative_visual_context",
                "reason": "No specialized evidence need was detected, so representative video frames are sufficient.",
                "source": "scene_frames",
                "selection_hint": "Prefer sharp, legible, non-transitional frames.",
            }
        )

    return {
        "query": query,
        "tokens": tokens,
        "needs": needs,
        "planner": {
            "name": "deterministic_keyword_planner",
            "version": 1,
        },
    }


def resolve_video_for_analysis(video: str, *, dry_run: bool) -> dict[str, Any]:
    """Resolve a user video value through the asset cache before analysis helpers run."""
    original = str(video)
    try:
        resolved = asset_cache.resolve_input(original, want="path")
    except Exception as exc:
        if not dry_run:
            raise
        return {
            "original": original,
            "resolved": original,
            "resolved_ok": False,
            "resolution_error": str(exc),
        }
    return {
        "original": original,
        "resolved": str(Path(resolved)),
        "resolved_ok": True,
        "resolution_error": None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create source-relevant thumbnail candidates for a video."
    )
    parser.add_argument("--video", required=True, help="Source video path or URL.")
    parser.add_argument("--query", required=True, help="Thumbnail direction or search query.")
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for evidence, generated thumbnails, manifests, and review artifacts.",
    )
    parser.add_argument(
        "--size",
        default=DEFAULT_SIZE,
        type=normalized_size,
        help=f"Thumbnail size as WIDTHxHEIGHT. Defaults to {DEFAULT_SIZE}.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help="Number of thumbnail candidates to plan or generate.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Image generation model. Defaults to {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--quality",
        default=DEFAULT_QUALITY,
        choices=("low", "medium", "high", "auto"),
        help=f"Image generation quality. Defaults to {DEFAULT_QUALITY}.",
    )
    parser.add_argument(
        "--output-format",
        default=DEFAULT_OUTPUT_FORMAT,
        choices=("png", "jpeg", "jpg", "webp"),
        help=f"Generated thumbnail image format. Defaults to {DEFAULT_OUTPUT_FORMAT}.",
    )
    parser.add_argument(
        "--visual-mode",
        default=DEFAULT_VISUAL_MODE,
        choices=("fast", "best"),
        help=f"Visual selection model tier for source evidence. Defaults to {DEFAULT_VISUAL_MODE}.",
    )
    parser.add_argument(
        "--reference-mode",
        default=DEFAULT_REFERENCE_MODE,
        choices=("auto", "always", "never"),
        help="Whether generated candidates should be refined with source reference packs.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=DEFAULT_MAX_CANDIDATES,
        help="Maximum video evidence candidates to pass into the visual selection contact sheet.",
    )
    parser.add_argument(
        "--previous-manifest",
        type=Path,
        help="Prior thumbnail manifest to use for feedback/refinement lineage.",
    )
    parser.add_argument(
        "--feedback",
        help="User feedback to apply when refining from --previous-manifest.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional env file used by downstream image or understanding calls.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write planning artifacts without media analysis, model calls, or image generation.",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.count < 1:
        parser.error("--count must be >= 1")
    if args.max_candidates < 1:
        parser.error("--max-candidates must be >= 1")
    if bool(args.feedback) and args.previous_manifest is None:
        parser.error("--feedback requires --previous-manifest")


def build_plan(args: argparse.Namespace, layout: dict[str, Path], video_resolution: dict[str, Any]) -> dict[str, Any]:
    evidence_plan = plan_evidence_needs(args.query)
    return {
        "tool": "thumbnail_maker",
        "version": 1,
        "mode": "dry-run" if args.dry_run else "run",
        "video": video_resolution,
        "query": args.query,
        "size": args.size,
        "count": args.count,
        "previous_manifest": str(args.previous_manifest) if args.previous_manifest else None,
        "feedback": args.feedback,
        "env_file": str(args.env_file) if args.env_file else None,
        "generation": {
            "model": args.model,
            "quality": args.quality,
            "output_format": args.output_format,
        },
        "source_selection": {
            "visual_mode": args.visual_mode,
            "reference_mode": args.reference_mode,
            "max_candidates": args.max_candidates,
        },
        "output_layout": {key: str(path) for key, path in layout.items()},
        "evidence_plan": evidence_plan,
        "planned_steps": [
            {
                "id": "resolve_video",
                "status": "complete" if video_resolution["resolved_ok"] else "warning",
                "artifact": "thumbnail-plan.json",
            },
            {
                "id": "plan_evidence",
                "status": "complete",
                "artifact": "evidence/evidence-plan.json",
            },
            {
                "id": "discover_video_evidence",
                "status": "pending",
                "artifact": "evidence/candidates.json",
            },
            {
                "id": "build_reference_pack",
                "status": "pending",
                "artifact": "evidence/reference-pack.json",
            },
            {
                "id": "generate_thumbnail_candidates",
                "status": "pending",
                "artifact": "thumbnail-manifest.json",
            },
        ],
    }


def write_planning_artifacts(plan: dict[str, Any], layout: dict[str, Path]) -> None:
    write_json(layout["root"] / "thumbnail-plan.json", plan)
    write_json(layout["evidence"] / "evidence-plan.json", plan["evidence_plan"])
    write_json(
        layout["review"] / "dry-run-summary.json",
        {
            "dry_run": plan["mode"] == "dry-run",
            "video": plan["video"],
            "query": plan["query"],
            "size": plan["size"],
            "count": plan["count"],
            "generation": plan["generation"],
            "source_selection": plan["source_selection"],
            "planned_artifacts": [
                "thumbnail-plan.json",
                "evidence/evidence-plan.json",
                "evidence/candidates.json",
                "evidence/query-selection.json",
                "evidence/reference-pack.json",
                "prompts/prompts.json",
                "thumbnail-manifest.json",
                "review/contact-sheet.jpg",
                "review/evidence-contact-sheet.jpg",
                "review/dry-run-summary.json",
            ],
            "skipped": [
                "media analysis",
                "visual model selection",
                "image generation",
            ],
        },
    )


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _format_seconds(seconds: float | int | None) -> str:
    if seconds is None:
        return ""
    whole = int(float(seconds))
    minutes, sec = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def _placeholder_contact_sheet(candidates: list[dict[str, Any]], out_path: Path, *, reason: str) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        out_path.write_bytes(MINIMAL_JPEG)
        return out_path
    cols = max(1, min(4, len(candidates) or 1))
    rows = max(1, math.ceil((len(candidates) or 1) / cols))
    tile_width = 420
    tile_height = 236
    sheet = Image.new("RGB", (cols * tile_width, rows * tile_height), (18, 18, 20))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
        small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 17)
    except OSError:
        font = ImageFont.load_default()
        small = ImageFont.load_default()
    items = candidates or [{"candidate_id": "planned", "label": "No candidate frames available yet"}]
    for index, candidate in enumerate(items, start=1):
        col = (index - 1) % cols
        row = (index - 1) // cols
        x = col * tile_width
        y = row * tile_height
        draw.rectangle((x, y, x + tile_width - 1, y + tile_height - 1), outline=(78, 78, 82), width=2)
        draw.rectangle((x, y, x + tile_width, y + 42), fill=(0, 0, 0))
        draw.text((x + 14, y + 10), f"Frame {index}", fill=(255, 255, 255), font=font)
        label = str(candidate.get("label") or candidate.get("candidate_id") or "")
        draw.text((x + 14, y + 64), label[:52], fill=(230, 230, 230), font=small)
        draw.text((x + 14, y + 92), reason[:52], fill=(168, 168, 172), font=small)
    sheet.save(out_path, quality=90)
    return out_path


def _write_candidate_contact_sheet(candidates: list[dict[str, Any]], out_path: Path) -> dict[str, Any]:
    frame_items: list[tuple[Path, str]] = []
    for candidate in candidates:
        frame_path = candidate.get("frame_path")
        if isinstance(frame_path, str) and Path(frame_path).is_file():
            label = _format_seconds(candidate.get("timestamp_sec"))
            frame_items.append((Path(frame_path), label))
    if not frame_items:
        path = _placeholder_contact_sheet(candidates, out_path, reason="dry-run or no extracted frame")
        return {"path": str(path), "mode": "placeholder", "frame_count": len(candidates)}
    try:
        from artagents.packs.builtin.visual_understand.run import _build_contact_sheet

        path = _build_contact_sheet(
            frame_items,
            out_path=out_path,
            cols=4,
            tile_width=360,
            label_prefix="Frame",
        )
        return {"path": str(path), "mode": "frames", "frame_count": len(frame_items)}
    except ImportError:
        path = _placeholder_contact_sheet(candidates, out_path, reason="Pillow unavailable")
        return {"path": str(path), "mode": "placeholder", "frame_count": len(candidates)}


def _planned_dry_run_candidates(args: argparse.Namespace, evidence_plan: dict[str, Any]) -> list[dict[str, Any]]:
    limit = min(args.max_candidates, DEFAULT_MAX_CANDIDATES)
    planned_count = max(1, min(limit, len(evidence_plan["needs"]) or 1))
    candidates: list[dict[str, Any]] = []
    needs = evidence_plan["needs"] or [{"id": "representative_visual_context"}]
    for index in range(planned_count):
        need = needs[index % len(needs)]
        candidates.append(
            {
                "candidate_id": f"ev-{index + 1:03d}",
                "index": index + 1,
                "source": "dry_run_plan",
                "status": "planned",
                "scene_index": None,
                "frame_index": None,
                "timestamp_sec": None,
                "frame_path": None,
                "label": str(need["id"]),
                "evidence_need": need,
            }
        )
    return candidates


def _load_or_create_scenes(video_path: Path, layout: dict[str, Path]) -> tuple[list[dict[str, Any]], Path, bool]:
    from artagents.packs.builtin.scenes import run as scenes_module

    scenes_path = layout["evidence"] / "scenes.json"
    csv_path = scenes_path.with_name("scenes.csv")
    if scenes_path.is_file():
        return load_json_file(scenes_path), scenes_path, True
    scenes = scenes_module.detect_scenes(video_path, threshold=27.0)
    scenes_module.write_outputs(scenes, scenes_path, csv_path)
    return scenes, scenes_path, False


def _load_or_create_shots(
    video_path: Path,
    scenes: list[dict[str, Any]],
    layout: dict[str, Path],
) -> tuple[list[dict[str, Any]], Path, bool]:
    from artagents.packs.builtin.shots import run as shots_module

    shots_dir = layout["evidence"] / "shots"
    shots_path = shots_dir / "shots.json"
    if shots_path.is_file():
        return load_json_file(shots_path), shots_path, True
    shots = shots_module.build_shots(video_path, scenes, shots_dir, per_scene=3)
    shots_path.write_text(json.dumps(shots, indent=2) + "\n", encoding="utf-8")
    return shots, shots_path, False


def _candidate_records(shots: list[dict[str, Any]], *, max_candidates: int) -> list[dict[str, Any]]:
    limit = min(max_candidates, DEFAULT_MAX_CANDIDATES)
    raw_candidates: list[dict[str, Any]] = []
    for shot in shots:
        scene_index = shot.get("scene_index")
        for frame_index, frame in enumerate(shot.get("frames") or [], start=1):
            timestamp = frame.get("timestamp")
            raw_candidates.append(
                {
                    "source": "shots",
                    "status": "available",
                    "scene_index": scene_index,
                    "frame_index": frame_index,
                    "timestamp_sec": float(timestamp) if timestamp is not None else None,
                    "frame_path": str(frame.get("path")) if frame.get("path") else None,
                    "label": f"scene {scene_index} frame {frame_index}",
                }
            )
    if len(raw_candidates) <= limit:
        selected = raw_candidates
    else:
        selected = []
        for slot in range(limit):
            index = round(slot * (len(raw_candidates) - 1) / (limit - 1)) if limit > 1 else 0
            selected.append(raw_candidates[index])
    candidates: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected, start=1):
        candidates.append({"candidate_id": f"ev-{index:03d}", "index": index, **candidate})
    return candidates


def _selection_prompt(query: str, candidates: list[dict[str, Any]]) -> str:
    numbered = [
        f"{candidate['index']}: {candidate.get('label', '')} at {_format_seconds(candidate.get('timestamp_sec'))}"
        for candidate in candidates
    ]
    return "\n".join(
        [
            "Select the most useful source frames for a YouTube-style thumbnail.",
            f"Thumbnail query: {query}",
            "Return compact JSON only: {\"selected_indices\":[1,2],\"reasons\":{\"1\":\"...\"}}.",
            "Candidates:",
            *numbered,
        ]
    )


def _parse_selected_indices(raw_text: str) -> tuple[list[int], str]:
    text = raw_text.strip()
    if not text:
        return [], "empty"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            numbers = [int(value) for value in re.findall(r"\b(?:frame|candidate)?\s*#?(\d{1,2})\b", text, flags=re.I)]
            return numbers, "regex" if numbers else "unparseable"
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return [], "unparseable"
    if isinstance(payload, dict):
        values = payload.get("selected_indices") or payload.get("selected") or payload.get("frames") or []
        if isinstance(values, list):
            indices: list[int] = []
            for value in values:
                if isinstance(value, int):
                    indices.append(value)
                elif isinstance(value, dict) and isinstance(value.get("index"), int):
                    indices.append(value["index"])
                elif isinstance(value, str) and value.strip().isdigit():
                    indices.append(int(value.strip()))
            return indices, "json"
    if isinstance(payload, list):
        return [int(value) for value in payload if isinstance(value, int)], "json"
    return [], "unparseable"


def _fallback_selection(candidates: list[dict[str, Any]], *, count: int, reason: str) -> dict[str, Any]:
    selected = candidates[: max(1, min(count, len(candidates)))] if candidates else []
    return {
        "mode": "fallback",
        "fallback": True,
        "fallback_reason": reason,
        "raw_result": None,
        "selected": [
            {
                "candidate_id": candidate["candidate_id"],
                "index": candidate["index"],
                "reason": "Deterministic fallback selected a bounded candidate from the sampled talk span.",
            }
            for candidate in selected
        ],
    }


def normalize_query_selection(
    raw_result: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    *,
    count: int,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        selection = _fallback_selection(candidates, count=count, reason="dry_run")
        selection["mode"] = "dry_run"
        return selection
    if raw_result is None:
        return _fallback_selection(candidates, count=count, reason="missing_model_result")
    answer = str(raw_result.get("answer") or "")
    indices, parse_mode = _parse_selected_indices(answer)
    by_index = {int(candidate["index"]): candidate for candidate in candidates}
    selected_candidates = []
    seen: set[int] = set()
    for index in indices:
        if index in seen or index not in by_index:
            continue
        seen.add(index)
        selected_candidates.append(by_index[index])
        if len(selected_candidates) >= count:
            break
    if not selected_candidates:
        selection = _fallback_selection(candidates, count=count, reason=f"model_output_{parse_mode}")
        selection["raw_result"] = raw_result
        return selection
    return {
        "mode": "visual_model",
        "fallback": False,
        "parse_mode": parse_mode,
        "raw_result": raw_result,
        "selected": [
            {
                "candidate_id": candidate["candidate_id"],
                "index": candidate["index"],
                "reason": "Selected by query-relevance visual pass.",
            }
            for candidate in selected_candidates
        ],
    }


def _run_visual_selection(
    args: argparse.Namespace,
    candidates: list[dict[str, Any]],
    contact_sheet_path: Path,
) -> dict[str, Any] | None:
    if not candidates:
        return None
    try:
        from artagents.packs.builtin.visual_understand import run as visual_understand
        from artagents.packs.builtin.generate_image.run import load_api_key

        model = visual_understand.MODEL_PRESETS[args.visual_mode]
        response = visual_understand._call_responses_api(
            api_key=load_api_key(args.env_file),
            model=model,
            query=_selection_prompt(args.query, candidates),
            image_path=contact_sheet_path,
            detail="low",
            max_output_tokens=500,
            timeout=120,
        )
        return {
            "model": model,
            "status": "ok",
            "answer": visual_understand._response_text(response),
            "usage": response.get("usage"),
            "response_id": response.get("id"),
        }
    except Exception as exc:
        return {
            "model": args.visual_mode,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "answer": "",
        }


def discover_video_evidence(
    args: argparse.Namespace,
    layout: dict[str, Path],
    plan: dict[str, Any],
) -> dict[str, Any]:
    candidates_path = layout["evidence"] / "candidates.json"
    selection_path = layout["evidence"] / "query-selection.json"
    contact_sheet_path = layout["review"] / "evidence-contact-sheet.jpg"
    reused: dict[str, bool] = {}

    if args.dry_run:
        candidates = _planned_dry_run_candidates(args, plan["evidence_plan"])
        scenes_path = None
        shots_path = None
    else:
        video_path = Path(plan["video"]["resolved"])
        scenes, scenes_path, reused_scenes = _load_or_create_scenes(video_path, layout)
        shots, shots_path, reused_shots = _load_or_create_shots(video_path, scenes, layout)
        reused = {"scenes": reused_scenes, "shots": reused_shots}
        candidates = _candidate_records(shots, max_candidates=args.max_candidates)

    contact_sheet = _write_candidate_contact_sheet(candidates, contact_sheet_path)
    candidates_payload = {
        "video": plan["video"],
        "query": args.query,
        "max_candidates": min(args.max_candidates, DEFAULT_MAX_CANDIDATES),
        "candidate_count": len(candidates),
        "bounded_by": "visual_understand.DEFAULT_MAX_IMAGES",
        "scenes_ref": str(scenes_path) if scenes_path else None,
        "shots_ref": str(shots_path) if shots_path else None,
        "reused": reused,
        "contact_sheet": contact_sheet,
        "candidates": candidates,
    }
    write_json(candidates_path, candidates_payload)

    raw_selection = None if args.dry_run else _run_visual_selection(args, candidates, contact_sheet_path)
    normalized = normalize_query_selection(
        raw_selection,
        candidates,
        count=max(1, min(args.count, len(candidates) or 1)),
        dry_run=args.dry_run,
    )
    selection_payload = {
        "query": args.query,
        "candidate_count": len(candidates),
        "contact_sheet": str(contact_sheet_path),
        "selection": normalized,
    }
    write_json(selection_path, selection_payload)
    return {
        "candidates": str(candidates_path),
        "query_selection": str(selection_path),
        "contact_sheet": str(contact_sheet_path),
    }


def _needs_composition_crops(plan: dict[str, Any], args: argparse.Namespace) -> bool:
    if args.reference_mode == "never":
        return False
    need_ids = {str(need.get("id")) for need in plan["evidence_plan"].get("needs", [])}
    if "speaker_or_person_framing" in need_ids:
        return True
    return args.reference_mode == "always"


def _crop_variants() -> list[dict[str, Any]]:
    return [
        {
            "kind": "composition_crop",
            "variant_id": "left_weighted",
            "label": "composition_crop left_weighted",
            "box_normalized": {"x": 0.0, "y": 0.0, "width": 0.78, "height": 1.0},
            "purpose": "Broad framing aid that leaves text room on the right.",
        },
        {
            "kind": "composition_crop",
            "variant_id": "center_weighted",
            "label": "composition_crop center_weighted",
            "box_normalized": {"x": 0.11, "y": 0.0, "width": 0.78, "height": 1.0},
            "purpose": "Broad centered framing aid for subject-forward compositions.",
        },
        {
            "kind": "composition_crop",
            "variant_id": "right_weighted",
            "label": "composition_crop right_weighted",
            "box_normalized": {"x": 0.22, "y": 0.0, "width": 0.78, "height": 1.0},
            "purpose": "Broad framing aid that leaves text room on the left.",
        },
    ]


def _copy_reference_frame(source_path: str | None, dest_path: Path) -> str | None:
    if not source_path:
        return None
    source = Path(source_path)
    if not source.is_file():
        return None
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(source.read_bytes())
    return str(dest_path)


def _materialize_crop(source_path: str | None, dest_path: Path, box: dict[str, float]) -> str | None:
    if not source_path:
        return None
    source = Path(source_path)
    if not source.is_file():
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        left = int(round(float(box["x"]) * image.width))
        top = int(round(float(box["y"]) * image.height))
        right = int(round((float(box["x"]) + float(box["width"])) * image.width))
        bottom = int(round((float(box["y"]) + float(box["height"])) * image.height))
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        image.crop((left, top, right, bottom)).save(dest_path, quality=92)
    return str(dest_path)


def build_reference_pack(
    args: argparse.Namespace,
    layout: dict[str, Path],
    plan: dict[str, Any],
) -> dict[str, Any]:
    candidates_payload = load_json_file(layout["evidence"] / "candidates.json")
    selection_payload = load_json_file(layout["evidence"] / "query-selection.json")
    candidates = candidates_payload.get("candidates") or []
    by_id = {candidate.get("candidate_id"): candidate for candidate in candidates}
    by_index = {candidate.get("index"): candidate for candidate in candidates}
    selected_records = selection_payload.get("selection", {}).get("selected") or []
    include_crops = _needs_composition_crops(plan, args)

    references: list[dict[str, Any]] = []
    for selected in selected_records:
        candidate = by_id.get(selected.get("candidate_id")) or by_index.get(selected.get("index"))
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate["candidate_id"])
        frame_path = candidate.get("frame_path")
        copied_frame = _copy_reference_frame(
            frame_path,
            layout["references"] / f"{candidate_id}_full_frame.jpg",
        )
        crops: list[dict[str, Any]] = []
        if include_crops:
            for crop in _crop_variants():
                crop_payload = dict(crop)
                crop_path = _materialize_crop(
                    frame_path,
                    layout["references"] / f"{candidate_id}_{crop['variant_id']}.jpg",
                    crop["box_normalized"],
                )
                crop_payload["path"] = crop_path
                crop_payload["materialized"] = crop_path is not None
                crops.append(crop_payload)
        references.append(
            {
                "candidate_id": candidate_id,
                "selection_index": selected.get("index"),
                "selection_reason": selected.get("reason"),
                "source": candidate.get("source"),
                "scene_index": candidate.get("scene_index"),
                "timestamp_sec": candidate.get("timestamp_sec"),
                "full_frame": {
                    "source_path": frame_path,
                    "path": copied_frame,
                    "materialized": copied_frame is not None,
                },
                "composition_crops": crops,
            }
        )

    payload = {
        "version": 1,
        "query": args.query,
        "video": plan["video"],
        "selection_ref": str(layout["evidence"] / "query-selection.json"),
        "candidates_ref": str(layout["evidence"] / "candidates.json"),
        "reference_mode": args.reference_mode,
        "composition_crop_policy": {
            "enabled": include_crops,
            "kind": "composition_crop",
            "note": "Fixed broad framing aids only; no face, person, or speaker detection is claimed.",
        },
        "references": references,
    }
    write_json(layout["evidence"] / "reference-pack.json", payload)
    return payload


def _load_previous_manifest(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = load_json_file(path.expanduser())
    return payload if isinstance(payload, dict) else {"candidates": payload}


def _previous_candidate_ids(previous_manifest: dict[str, Any] | None) -> list[str]:
    if not previous_manifest:
        return []
    values: list[str] = []
    for item in previous_manifest.get("candidates") or previous_manifest.get("thumbnails") or []:
        if isinstance(item, dict):
            candidate_id = item.get("candidate_id") or item.get("id")
            if candidate_id:
                values.append(str(candidate_id))
    return values


def _reference_summary(reference: dict[str, Any]) -> str:
    parts = []
    if reference.get("scene_index") is not None:
        parts.append(f"scene {reference['scene_index']}")
    if reference.get("timestamp_sec") is not None:
        parts.append(f"at {_format_seconds(reference['timestamp_sec'])}")
    reason = reference.get("selection_reason")
    if reason:
        parts.append(f"selection reason: {reason}")
    crops = reference.get("composition_crops") or []
    if crops:
        parts.append(
            "use source as broad composition guidance; available crop hints: "
            + ", ".join(str(crop.get("label")) for crop in crops if crop.get("label"))
        )
    return "; ".join(parts) or "representative source evidence"


def _prompt_text(
    *,
    query: str,
    reference: dict[str, Any] | None,
    size: str,
    feedback: str | None,
    previous_candidate_id: str | None,
) -> str:
    lines = [
        "Create a high-impact YouTube thumbnail.",
        f"User thumbnail direction: {query}",
        f"Canvas: {size}. Use bold, readable composition with clear subject/background separation.",
    ]
    if reference is not None:
        lines.append(f"Source evidence: {_reference_summary(reference)}.")
        full_frame = reference.get("full_frame") or {}
        if full_frame.get("source_path"):
            lines.append(f"Reference frame path for reviewer context: {full_frame['source_path']}.")
    if feedback:
        lineage = f" for prior candidate {previous_candidate_id}" if previous_candidate_id else ""
        lines.append(f"Apply refinement feedback{lineage}: {feedback}")
    lines.append("Avoid clutter. Leave intentional negative space for short title text when useful.")
    return "\n".join(lines)


def build_prompt_jobs(
    args: argparse.Namespace,
    layout: dict[str, Path],
    plan: dict[str, Any],
    reference_pack: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    previous_manifest = _load_previous_manifest(args.previous_manifest)
    previous_ids = _previous_candidate_ids(previous_manifest)
    references = list(reference_pack.get("references") or [])
    if not references:
        references = [{"candidate_id": "ev-000", "selection_reason": "No selected source evidence was available."}]
    jobs: list[dict[str, Any]] = []
    for index in range(args.count):
        reference = references[index % len(references)]
        candidate_id = f"thumb-{index + 1:03d}"
        previous_candidate_id = previous_ids[index % len(previous_ids)] if previous_ids else None
        job = {
            "candidate_id": candidate_id,
            "evidence_candidate_id": reference.get("candidate_id"),
            "prompt": _prompt_text(
                query=args.query,
                reference=reference,
                size=args.size,
                feedback=args.feedback,
                previous_candidate_id=previous_candidate_id,
            ),
            "model": args.model,
            "size": args.size,
            "quality": args.quality,
            "output_format": args.output_format,
            "n": 1,
            "out": f"{candidate_id}.{args.output_format}",
        }
        if previous_candidate_id:
            job["refines_candidate_id"] = previous_candidate_id
        jobs.append(job)
    write_json(layout["prompts"] / "prompts.json", {"version": 1, "jobs": jobs})
    prompt_list = [
        {key: value for key, value in job.items() if key in {"prompt", "model", "size", "quality", "output_format", "n", "out"}}
        for job in jobs
    ]
    (layout["prompts"] / "generate-image-prompts.json").write_text(
        json.dumps(prompt_list, indent=2) + "\n",
        encoding="utf-8",
    )

    refinement = None
    if args.previous_manifest is not None or args.feedback:
        refinement = {
            "previous_manifest": str(args.previous_manifest) if args.previous_manifest else None,
            "feedback": args.feedback,
            "lineage": [
                {
                    "candidate_id": job["candidate_id"],
                    "refines_candidate_id": job.get("refines_candidate_id"),
                    "evidence_candidate_id": job.get("evidence_candidate_id"),
                }
                for job in jobs
            ],
        }
        write_json(layout["root"] / "refinement.json", refinement)
    return jobs, refinement


def _planned_generated_outputs(jobs: list[dict[str, Any]], layout: dict[str, Path]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for job in jobs:
        output_path = layout["generated"] / str(job["out"])
        outputs.append(
            {
                "candidate_id": job["candidate_id"],
                "path": str(output_path),
                "exists": output_path.is_file(),
                "dry_run": True,
            }
        )
        write_json(
            layout["generated"] / f"{job['candidate_id']}.request.json",
            {
                "candidate_id": job["candidate_id"],
                "endpoint": "generate_image.py",
                "prompt": job["prompt"],
                "model": job["model"],
                "size": job["size"],
                "quality": job["quality"],
                "output_format": job["output_format"],
                "planned_output": str(output_path),
            },
        )
    return outputs


def _run_image_generation(
    args: argparse.Namespace,
    layout: dict[str, Path],
    jobs: list[dict[str, Any]],
) -> tuple[int | None, list[dict[str, Any]]]:
    if args.dry_run:
        return None, _planned_generated_outputs(jobs, layout)
    from artagents.packs.builtin.generate_image import run as generate_image

    manifest_path = layout["generated"] / "generate-image-manifest.json"
    returncode = generate_image.main(
        [
            "--prompts-file",
            str(layout["prompts"] / "generate-image-prompts.json"),
            "--model",
            args.model,
            "--size",
            args.size,
            "--quality",
            args.quality,
            "--output-format",
            args.output_format,
            "--out-dir",
            str(layout["generated"]),
            "--manifest",
            str(manifest_path),
            *(["--env-file", str(args.env_file)] if args.env_file else []),
        ]
    )
    generated_manifest = load_json_file(manifest_path) if manifest_path.is_file() else []
    outputs: list[dict[str, Any]] = []
    for job, item in zip(jobs, generated_manifest):
        output_paths = item.get("outputs") if isinstance(item, dict) else []
        outputs.append(
            {
                "candidate_id": job["candidate_id"],
                "path": output_paths[0] if output_paths else str(layout["generated"] / str(job["out"])),
                "exists": bool(output_paths),
                "dry_run": False,
                "usage": item.get("usage") if isinstance(item, dict) else None,
            }
        )
    if not outputs:
        outputs = [
            {
                "candidate_id": job["candidate_id"],
                "path": str(layout["generated"] / str(job["out"])),
                "exists": False,
                "dry_run": False,
            }
            for job in jobs
        ]
    return returncode, outputs


def _write_final_contact_sheet(outputs: list[dict[str, Any]], out_path: Path) -> dict[str, Any]:
    frame_items: list[tuple[Path, str]] = []
    for item in outputs:
        path = Path(str(item.get("path")))
        if path.is_file():
            frame_items.append((path, str(item.get("candidate_id") or "")))
    if not frame_items:
        placeholder_items = [
            {"candidate_id": item.get("candidate_id"), "label": str(item.get("path") or "")}
            for item in outputs
        ]
        path = _placeholder_contact_sheet(placeholder_items, out_path, reason="planned thumbnail output")
        return {"path": str(path), "mode": "placeholder", "image_count": len(outputs)}
    try:
        from artagents.packs.builtin.visual_understand.run import _build_contact_sheet

        path = _build_contact_sheet(
            frame_items,
            out_path=out_path,
            cols=4,
            tile_width=360,
            label_prefix="Thumbnail",
        )
        return {"path": str(path), "mode": "images", "image_count": len(frame_items)}
    except ImportError:
        path = _placeholder_contact_sheet(
            [{"candidate_id": item.get("candidate_id"), "label": str(item.get("path") or "")} for item in outputs],
            out_path,
            reason="Pillow unavailable",
        )
        return {"path": str(path), "mode": "placeholder", "image_count": len(outputs)}


def generate_thumbnail_outputs(
    args: argparse.Namespace,
    layout: dict[str, Path],
    plan: dict[str, Any],
    reference_pack: dict[str, Any],
) -> dict[str, Any]:
    jobs, refinement = build_prompt_jobs(args, layout, plan, reference_pack)
    generation_returncode, outputs = _run_image_generation(args, layout, jobs)
    contact_sheet = _write_final_contact_sheet(outputs, layout["review"] / "contact-sheet.jpg")
    candidates = []
    for job in jobs:
        output = next((item for item in outputs if item.get("candidate_id") == job["candidate_id"]), {})
        candidates.append(
            {
                "candidate_id": job["candidate_id"],
                "evidence_candidate_id": job.get("evidence_candidate_id"),
                "refines_candidate_id": job.get("refines_candidate_id"),
                "prompt": job["prompt"],
                "generated": output,
            }
        )
    manifest = {
        "version": 1,
        "mode": plan["mode"],
        "query": args.query,
        "size": args.size,
        "count": args.count,
        "video": plan["video"],
        "prompt_jobs_ref": str(layout["prompts"] / "prompts.json"),
        "reference_pack_ref": str(layout["evidence"] / "reference-pack.json"),
        "contact_sheet": contact_sheet,
        "generation_returncode": generation_returncode,
        "refinement_ref": str(layout["root"] / "refinement.json") if refinement else None,
        "candidates": candidates,
    }
    write_json(layout["root"] / "thumbnail-manifest.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)

    layout = build_output_layout(args.out)
    ensure_output_layout(layout)

    video_resolution = resolve_video_for_analysis(args.video, dry_run=args.dry_run)
    plan = build_plan(args, layout, video_resolution)
    write_planning_artifacts(plan, layout)
    discover_video_evidence(args, layout, plan)
    reference_pack = build_reference_pack(args, layout, plan)
    generate_thumbnail_outputs(args, layout, plan, reference_pack)

    if args.dry_run:
        print(f"wrote_thumbnail_plan={layout['root'] / 'thumbnail-plan.json'}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
