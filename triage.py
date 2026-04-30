#!/usr/bin/env python3
"""Claude-powered first-pass scene triage over keyframe batches."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from llm_clients import ClaudeClient, build_claude_client

TRIAGE_VERSION = 1
FORBIDDEN_TIME_KEYS = frozenset({"start", "end", "timestamp", "seconds", "time", "src_start", "src_end", "from", "to", "at"})
RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "scene_id": {"type": "string"},
                    "triage_score": {"type": "integer", "minimum": 1, "maximum": 5},
                    "triage_tag": {"type": "string"},
                },
                "required": ["scene_id", "triage_score", "triage_tag"],
            },
        }
    },
    "required": ["entries"],
}
SYSTEM_PROMPT = (
    "You are triaging source-video scenes for later pool construction. "
    "Rate only the provided scene_ids. Never return timestamps or numeric ranges."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def scene_id_for(scene: dict[str, Any]) -> str:
    return f"scene_{int(scene['index']):03d}"


def validate_scene_triage(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("scene_triage payload must be an object")
    if payload.get("version") != TRIAGE_VERSION:
        raise ValueError(f"scene_triage.version must be {TRIAGE_VERSION}")
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.endswith("Z"):
        raise ValueError("scene_triage.generated_at must be a UTC timestamp ending in 'Z'")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("scene_triage.entries must be a list")
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        path = f"scene_triage.entries[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{path} must be an object")
        if set(entry) != {"scene_id", "triage_score", "triage_tag"}:
            raise ValueError(f"{path} has unexpected keys")
        scene_id = entry.get("scene_id")
        triage_score = entry.get("triage_score")
        triage_tag = entry.get("triage_tag")
        if not isinstance(scene_id, str) or not scene_id:
            raise ValueError(f"{path}.scene_id must be a non-empty string")
        if scene_id in seen_ids:
            raise ValueError(f"{path}.scene_id {scene_id!r} is duplicated")
        seen_ids.add(scene_id)
        if not isinstance(triage_score, int) or triage_score < 0 or triage_score > 5:
            raise ValueError(f"{path}.triage_score must be an integer from 0 to 5")
        if not isinstance(triage_tag, str) or not triage_tag:
            raise ValueError(f"{path}.triage_tag must be a non-empty string")


def _resolve_frame_path(frame_path: str, shots_dir: Path) -> Path:
    path = Path(frame_path)
    return path if path.is_absolute() else (shots_dir / path).resolve()


def _shot_map(shots: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    mapping: dict[int, dict[str, Any]] = {}
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        scene_index = shot.get("scene_index")
        if isinstance(scene_index, int):
            mapping[scene_index] = shot
    return mapping


def _scene_prompt(chunk: list[dict[str, Any]]) -> str:
    lines = [
        "Review the labeled keyframes for each scene_id and return JSON only.",
        "Score keep potential from 1 to 5 and provide a short triage_tag.",
        "Never return timestamps, durations, indexes, or any numeric ranges.",
        "",
        "Scenes in this batch:",
    ]
    for scene in chunk:
        lines.append(f"- {scene_id_for(scene)}")
    return "\n".join(lines)


def _attachments_for_chunk(chunk: list[dict[str, Any]], shots_by_scene: dict[int, dict[str, Any]], shots_dir: Path) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for scene in chunk:
        shot = shots_by_scene.get(int(scene["index"]))
        if not isinstance(shot, dict):
            continue
        frames = shot.get("frames")
        if not isinstance(frames, list):
            continue
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            frame_path = frame.get("path")
            if not isinstance(frame_path, str):
                continue
            resolved = _resolve_frame_path(frame_path, shots_dir)
            attachments.append(
                {
                    "type": "image",
                    "source": {"type": "path", "path": str(resolved)},
                    "label": scene_id_for(scene),
                }
            )
    return attachments


def build_triage(
    scenes: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    shots_dir: Path,
    *,
    client: ClaudeClient,
    grid_size: int = 20,
    model: str = "claude-haiku-4-5-20251001",
) -> dict[str, Any]:
    if grid_size <= 0:
        raise ValueError("grid_size must be > 0")
    shots_by_scene = _shot_map(shots)
    entries: list[dict[str, Any]] = []
    batch: list[dict[str, Any]] = []
    for scene in scenes:
        duration = float(scene.get("duration", float(scene.get("end", 0.0)) - float(scene.get("start", 0.0))))
        if duration < 0.3 or duration > 20.0:
            entries.append(
                {
                    "scene_id": scene_id_for(scene),
                    "triage_score": 0,
                    "triage_tag": "hard_filtered",
                }
            )
            continue
        batch.append(scene)
        if len(batch) < grid_size:
            continue
        response = client.complete_json(
            model=model,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": _scene_prompt(batch)}, *_attachments_for_chunk(batch, shots_by_scene, shots_dir)],
                }
            ],
            response_schema=RESPONSE_SCHEMA,
            max_tokens=2000,
        )
        raw_entries = response.get("entries")
        if not isinstance(raw_entries, list):
            raise ValueError("Claude triage response is missing entries")
        entries.extend(raw_entries)
        batch = []
    if batch:
        response = client.complete_json(
            model=model,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": _scene_prompt(batch)}, *_attachments_for_chunk(batch, shots_by_scene, shots_dir)],
                }
            ],
            response_schema=RESPONSE_SCHEMA,
            max_tokens=2000,
        )
        raw_entries = response.get("entries")
        if not isinstance(raw_entries, list):
            raise ValueError("Claude triage response is missing entries")
        entries.extend(raw_entries)

    # Claude occasionally emits the same scene_id twice across batch responses.
    # Keep the first occurrence and log the dupes rather than aborting the run.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    dupes: list[str] = []
    for entry in entries:
        if isinstance(entry, dict):
            scene_id = entry.get("scene_id")
            if isinstance(scene_id, str) and scene_id in seen:
                dupes.append(scene_id)
                continue
            if isinstance(scene_id, str):
                seen.add(scene_id)
        deduped.append(entry)
    if dupes:
        print(f"triage: dropped {len(dupes)} duplicate entries from Claude response ({', '.join(dupes[:5])}{'…' if len(dupes) > 5 else ''})", flush=True)
    payload = {"version": TRIAGE_VERSION, "generated_at": _utc_now(), "entries": deduped}
    validate_scene_triage(payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run first-pass Claude scene triage over shot keyframes.")
    parser.add_argument("--scenes", type=Path, required=True)
    parser.add_argument("--shots", type=Path, required=True)
    parser.add_argument("--shots-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", dest="env_file", type=Path)
    parser.add_argument("--model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--grid-size", type=int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    scenes = json.loads(args.scenes.read_text(encoding="utf-8"))
    shots = json.loads(args.shots.read_text(encoding="utf-8"))
    payload = build_triage(
        scenes,
        shots,
        args.shots_dir.resolve(),
        client=build_claude_client(args.env_file),
        grid_size=args.grid_size,
        model=args.model,
    )
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "scene_triage.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
