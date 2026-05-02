#!/usr/bin/env python3
"""Gemini-powered deep scene descriptions for triage survivors."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ...audit import register_outputs
from ...llm_clients import GeminiClient, build_gemini_client

SCENE_DESCRIPTIONS_VERSION = 1
FORBIDDEN_TIME_KEYS = frozenset({"start", "end", "timestamp", "seconds", "time", "src_start", "src_end", "from", "to", "at"})
RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "description": {"type": "string"},
        "mood": {"type": "string"},
        "motion_level": {"type": "string", "enum": ["low", "med", "high"]},
        "speaker_visible": {"type": "boolean"},
        "dialogue_salient": {"type": "boolean"},
        "motion_tags": {"type": "array", "items": {"type": "string"}},
        "mood_tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "description",
        "mood",
        "motion_level",
        "speaker_visible",
        "dialogue_salient",
        "motion_tags",
        "mood_tags",
    ],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def scene_id_for(scene: dict[str, Any]) -> str:
    return f"scene_{int(scene['index']):03d}"


def validate_scene_descriptions(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("scene_descriptions payload must be an object")
    if payload.get("version") != SCENE_DESCRIPTIONS_VERSION:
        raise ValueError(f"scene_descriptions.version must be {SCENE_DESCRIPTIONS_VERSION}")
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.endswith("Z"):
        raise ValueError("scene_descriptions.generated_at must be a UTC timestamp ending in 'Z'")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("scene_descriptions.entries must be a list")
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        path = f"scene_descriptions.entries[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{path} must be an object")
        required = {
            "scene_id",
            "description",
            "mood",
            "motion_level",
            "speaker_visible",
            "dialogue_salient",
            "motion_tags",
            "mood_tags",
            "deep_score",
        }
        if not required.issubset(entry):
            raise ValueError(f"{path} is missing required keys")
        scene_id = entry.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id:
            raise ValueError(f"{path}.scene_id must be a non-empty string")
        if scene_id in seen_ids:
            raise ValueError(f"{path}.scene_id {scene_id!r} is duplicated")
        seen_ids.add(scene_id)
        if entry.get("motion_level") not in {"low", "med", "high"}:
            raise ValueError(f"{path}.motion_level must be one of low|med|high")
        for field in ("description", "mood"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                raise ValueError(f"{path}.{field} must be a non-empty string")
        for field in ("speaker_visible", "dialogue_salient"):
            if not isinstance(entry.get(field), bool):
                raise ValueError(f"{path}.{field} must be a boolean")
        for field in ("motion_tags", "mood_tags"):
            value = entry.get(field)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{path}.{field} must be a list of strings")
        deep_score = entry.get("deep_score")
        if not isinstance(deep_score, (int, float)) or deep_score < 0 or deep_score > 1:
            raise ValueError(f"{path}.deep_score must be a float from 0 to 1")


def _triage_map(triage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = triage.get("entries") if isinstance(triage, dict) else None
    if not isinstance(entries, list):
        raise ValueError("triage payload must contain entries")
    mapping: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("scene_id"), str):
            mapping[entry["scene_id"]] = entry
    return mapping


def _existing_entry_map(existing: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    entries = existing.get("entries") if isinstance(existing, dict) else None
    if not isinstance(entries, list):
        return {}
    mapping: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("scene_id"), str):
            mapping[entry["scene_id"]] = entry
    return mapping


def _selection(scenes: list[dict[str, Any]], triage_map: dict[str, dict[str, Any]], top_n: int, min_triage_score: int) -> list[dict[str, Any]]:
    eligible = [
        scene
        for scene in scenes
        if int(triage_map.get(scene_id_for(scene), {}).get("triage_score", 0)) >= min_triage_score
    ]
    eligible.sort(
        key=lambda scene: (
            int(triage_map[scene_id_for(scene)]["triage_score"]),
            float(scene.get("duration", float(scene.get("end", 0.0)) - float(scene.get("start", 0.0)))),
        ),
        reverse=True,
    )
    return eligible[:top_n]


def extract_scene_clip(video: Path, start_sec: float, end_sec: float, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(start_sec),
            "-to",
            str(end_sec),
            "-i",
            str(video),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "24",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(out_path),
        ],
        check=True,
    )
    return out_path


def _scene_prompt(scene_id: str) -> str:
    return (
        f"Describe {scene_id} for later pool building. "
        "Return JSON only with description, mood, motion_level, speaker_visible, dialogue_salient, motion_tags, and mood_tags. "
        "Never return timestamps, seconds, or source ranges."
    )


def _compute_deep_score(response: dict[str, Any]) -> float:
    # Composite favoring strong motion, visible speakers, and scenes that feel editorially salient.
    motion_weight = {"low": 0.25, "med": 0.55, "high": 0.85}[response["motion_level"]]
    speaker_weight = 0.1 if response["speaker_visible"] else 0.0
    dialogue_weight = 0.1 if response["dialogue_salient"] else 0.0
    tag_bonus = min(0.15, 0.03 * (len(response["motion_tags"]) + len(response["mood_tags"])))
    return round(min(1.0, motion_weight + speaker_weight + dialogue_weight + tag_bonus), 3)


def build_scene_descriptions(
    scenes: list[dict[str, Any]],
    triage: dict[str, Any],
    video: Path,
    *,
    client: GeminiClient,
    top_n: int,
    min_triage_score: int = 3,
    model: str = "gemini-2.5-pro",
    out_dir: Path | None = None,
) -> dict[str, Any]:
    if top_n <= 0:
        raise ValueError("top_n must be > 0")
    out_dir = (out_dir or video.parent).resolve()
    cache_dir = out_dir / "_describe_cache"
    existing_path = out_dir / "scene_descriptions.json"
    existing_payload = json.loads(existing_path.read_text(encoding="utf-8")) if existing_path.is_file() else None
    existing_map = _existing_entry_map(existing_payload)
    triage_map = _triage_map(triage)
    selected = _selection(scenes, triage_map, top_n, min_triage_score)
    entries: list[dict[str, Any]] = []
    for scene in selected:
        scene_id = scene_id_for(scene)
        cache_path = cache_dir / f"{scene_id}.mp4"
        if cache_path.is_file() and scene_id in existing_map:
            entries.append(dict(existing_map[scene_id]))
            continue
        extract_scene_clip(video.resolve(), float(scene["start"]), float(scene["end"]), cache_path)
        response = client.describe_video(
            model=model,
            video_path=cache_path,
            prompt=_scene_prompt(scene_id),
            response_schema=RESPONSE_SCHEMA,
        )
        entry = {
            "scene_id": scene_id,
            "description": response["description"],
            "mood": response["mood"],
            "motion_level": response["motion_level"],
            "speaker_visible": response["speaker_visible"],
            "dialogue_salient": response["dialogue_salient"],
            "motion_tags": response["motion_tags"],
            "mood_tags": response["mood_tags"],
            "deep_score": _compute_deep_score(response),
        }
        entries.append(entry)
    payload = {"version": SCENE_DESCRIPTIONS_VERSION, "generated_at": _utc_now(), "entries": entries}
    validate_scene_descriptions(payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Gemini deep descriptions on top-ranked triage survivors.")
    parser.add_argument("--scenes", type=Path, required=True)
    parser.add_argument("--triage", type=Path, required=True)
    parser.add_argument("--video", type=str, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=40)
    parser.add_argument("--env-file", dest="env_file", type=Path)
    parser.add_argument("--model", default="gemini-2.5-pro")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from ..asset_cache import run as asset_cache; args.video = Path(asset_cache.resolve_input(args.video, want="path"))
    scenes = json.loads(args.scenes.read_text(encoding="utf-8"))
    triage = json.loads(args.triage.read_text(encoding="utf-8"))
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = build_scene_descriptions(
        scenes,
        triage,
        args.video.resolve(),
        client=build_gemini_client(args.env_file),
        top_n=args.top_n,
        model=args.model,
        out_dir=out_dir,
    )
    out_path = out_dir / "scene_descriptions.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    register_outputs(
        stage="scene_describe",
        outputs=[("scene_descriptions", out_path, "Scene descriptions")],
        metadata={"model": args.model, "top_n": args.top_n},
    )
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
