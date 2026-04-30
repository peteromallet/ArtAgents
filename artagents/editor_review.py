#!/usr/bin/env python3
"""Rendered-cut editor review helpers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from .arrange import pool_digest
from .llm_clients import build_claude_client
from .timeline import load_arrangement, load_metadata, load_pool
from .transcribe import load_api_key
from ._paths import REPO_ROOT

EDITOR_ACTIONS = (
    "accept",
    "micro-fix",
    "swap",
    "reorder",
    "insert-stinger",
    "needs-better-pool-entry",
)
EDITOR_PRIORITIES = ("high", "medium", "low")
DEFAULT_MODEL = "claude-sonnet-4-6"

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "iteration": {"type": "integer", "minimum": 1, "maximum": 2},
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "clip_order": {"type": "integer"},
                    "clip_uuid": {"type": "string", "pattern": "^[0-9a-f]{8}$"},
                    "observation": {"type": "string"},
                    "brief_impact": {"type": "string"},
                    "action": {"type": "string", "enum": list(EDITOR_ACTIONS)},
                    "action_detail": {
                        "anyOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "trim_delta_start_sec": {"type": "number"},
                                    "trim_delta_end_sec": {"type": "number"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["trim_delta_start_sec", "trim_delta_end_sec", "reason"],
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "candidate_pool_id": {"type": "string"},
                                    "role": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["candidate_pool_id", "role", "reason"],
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "new_order": {"type": "integer"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["new_order", "reason"],
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "after_clip_order": {"type": "integer"},
                                    "candidate_pool_id": {"type": "string"},
                                    "duration_sec": {"type": "number"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["after_clip_order", "candidate_pool_id", "duration_sec", "reason"],
                            },
                            {
                                "type": "object",
                                "properties": {"reason": {"type": "string"}},
                                "required": ["reason"],
                            },
                            {"type": "null"},
                        ]
                    },
                    "priority": {"type": "string", "enum": list(EDITOR_PRIORITIES)},
                    "candidate_pool_id": {"type": ["string", "null"]},
                },
                "required": [
                    "clip_order",
                    "clip_uuid",
                    "observation",
                    "brief_impact",
                    "action",
                    "action_detail",
                    "priority",
                    "candidate_pool_id",
                ],
            },
        },
        "verdict": {"type": "string", "enum": ["ship", "iterate", "rework"]},
        "ship_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["iteration", "notes", "verdict", "ship_confidence"],
}


def _arrangement_orders(arrangement: dict[str, Any]) -> set[int]:
    clips = arrangement.get("clips")
    if not isinstance(clips, list):
        raise ValueError("arrangement.clips must be a list")
    orders: set[int] = set()
    for index, clip in enumerate(clips):
        if not isinstance(clip, dict):
            raise ValueError(f"arrangement.clips[{index}] must be an object")
        order = clip.get("order")
        if not isinstance(order, int):
            raise ValueError(f"arrangement.clips[{index}].order must be an integer")
        orders.add(order)
    return orders


def _arrangement_order_uuid_map(arrangement: dict[str, Any]) -> dict[int, str]:
    clips = arrangement.get("clips")
    if not isinstance(clips, list):
        raise ValueError("arrangement.clips must be a list")
    result: dict[int, str] = {}
    for index, clip in enumerate(clips):
        if not isinstance(clip, dict):
            raise ValueError(f"arrangement.clips[{index}] must be an object")
        order = clip.get("order")
        if not isinstance(order, int):
            raise ValueError(f"arrangement.clips[{index}].order must be an integer")
        clip_uuid = clip.get("uuid")
        if not isinstance(clip_uuid, str) or re.fullmatch(r"[0-9a-f]{8}", clip_uuid) is None:
            raise ValueError(f"arrangement.clips[{index}].uuid must be 8 lowercase hex characters")
        result[order] = clip_uuid
    return result


def _validate_note_uuid_references(notes: list[Any], arrangement: dict[str, Any]) -> dict[int, str]:
    order_to_uuid = _arrangement_order_uuid_map(arrangement)
    valid_uuids = set(order_to_uuid.values())
    for index, note in enumerate(notes):
        if not isinstance(note, dict):
            continue
        clip_order = note.get("clip_order")
        if not isinstance(clip_order, int):
            continue
        clip_uuid = note.get("clip_uuid")
        if not isinstance(clip_uuid, str) or re.fullmatch(r"[0-9a-f]{8}", clip_uuid) is None:
            raise ValueError(f"editor_review.notes[{index}].clip_uuid must be 8 lowercase hex characters")
        if clip_uuid not in valid_uuids:
            raise ValueError(f"editor_review.notes[{index}].clip_uuid {clip_uuid!r} is not in arrangement")
        if clip_order not in order_to_uuid:
            raise ValueError(f"editor_review.notes[{index}].clip_order {clip_order!r} is not in arrangement")
        if order_to_uuid[clip_order] != clip_uuid:
            raise ValueError(
                f"editor_review.notes[{index}].clip_uuid {clip_uuid!r} does not match clip_order {clip_order!r}"
            )
    return order_to_uuid


def _require_detail(note: dict[str, Any], action: str) -> dict[str, Any]:
    detail = note.get("action_detail")
    if not isinstance(detail, dict):
        raise ValueError(f"{action} note requires action_detail object")
    return detail


def _require_numeric(detail: dict[str, Any], field: str, action: str) -> None:
    if not isinstance(detail.get(field), (int, float)):
        raise ValueError(f"{action} action_detail.{field} must be numeric")


def _require_detail_keys(detail: dict[str, Any], action: str, expected: set[str]) -> None:
    missing = expected - set(detail)
    if missing:
        raise ValueError(f"{action} action_detail missing required keys: {sorted(missing)}")


def _validate_editor_notes(payload: dict[str, Any], arrangement: dict[str, Any]) -> None:
    """Validate editor-review semantics that are awkward to express in JSON Schema."""

    notes = payload.get("notes")
    if not isinstance(notes, list):
        raise ValueError("editor_review.notes must be a list")
    order_to_uuid = _validate_note_uuid_references(notes, arrangement)
    valid_orders = set(order_to_uuid)

    for index, note in enumerate(notes):
        if not isinstance(note, dict):
            raise ValueError(f"editor_review.notes[{index}] must be an object")
        action = note.get("action")
        if action not in EDITOR_ACTIONS:
            raise ValueError(f"editor_review.notes[{index}].action is invalid")
        clip_order = note.get("clip_order")
        if not isinstance(clip_order, int):
            raise ValueError(f"editor_review.notes[{index}].clip_order must be an integer")

        if action == "insert-stinger":
            detail = _require_detail(note, action)
            _require_detail_keys(detail, action, {"after_clip_order", "candidate_pool_id", "duration_sec", "reason"})
            after_clip_order = detail.get("after_clip_order")
            if not isinstance(after_clip_order, int) or after_clip_order not in valid_orders:
                raise ValueError("insert-stinger action_detail.after_clip_order must reference an existing clip order")
            candidate_pool_id = detail.get("candidate_pool_id")
            if not isinstance(candidate_pool_id, str) or not candidate_pool_id:
                raise ValueError("insert-stinger action_detail.candidate_pool_id must be a non-empty string")
            _require_numeric(detail, "duration_sec", action)
            continue

        if action == "micro-fix":
            detail = _require_detail(note, action)
            _require_detail_keys(detail, action, {"trim_delta_start_sec", "trim_delta_end_sec", "reason"})
            _require_numeric(detail, "trim_delta_start_sec", action)
            _require_numeric(detail, "trim_delta_end_sec", action)
        elif action == "swap":
            detail = _require_detail(note, action)
            _require_detail_keys(detail, action, {"candidate_pool_id", "role", "reason"})
            candidate_pool_id = note.get("candidate_pool_id")
            if not isinstance(candidate_pool_id, str) or not candidate_pool_id:
                raise ValueError("swap note requires candidate_pool_id")
            if detail.get("candidate_pool_id") != candidate_pool_id:
                raise ValueError("swap action_detail.candidate_pool_id must match note candidate_pool_id")
            if not isinstance(detail.get("role"), str) or not detail["role"]:
                raise ValueError("swap action_detail.role must be a non-empty string")
        elif action == "reorder":
            detail = _require_detail(note, action)
            _require_detail_keys(detail, action, {"new_order", "reason"})
            new_order = detail.get("new_order")
            if not isinstance(new_order, int):
                raise ValueError("reorder action_detail.new_order must be an integer")
        elif action == "needs-better-pool-entry":
            detail = _require_detail(note, action)
            _require_detail_keys(detail, action, {"reason"})
            if not isinstance(detail.get("reason"), str) or not detail["reason"].strip():
                raise ValueError("needs-better-pool-entry action_detail.reason must be a non-empty string")
        elif action == "accept" and note.get("action_detail") is not None:
            raise ValueError("accept action_detail must be null")


def _validate_review_payload_shape(payload: dict[str, Any], arrangement: dict[str, Any] | None = None) -> None:
    if not isinstance(payload, dict):
        raise ValueError("editor_review payload must be an object")
    allowed = set(RESPONSE_SCHEMA["properties"])
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"editor_review payload has unknown keys: {unknown}")
    for field in RESPONSE_SCHEMA["required"]:
        if field not in payload:
            raise ValueError(f"editor_review payload missing required field {field!r}")
    iteration = payload.get("iteration")
    if not isinstance(iteration, int) or not 1 <= iteration <= 2:
        raise ValueError("editor_review.iteration must be an integer between 1 and 2")
    notes = payload.get("notes")
    if not isinstance(notes, list):
        raise ValueError("editor_review.notes must be a list")
    note_allowed = set(RESPONSE_SCHEMA["properties"]["notes"]["items"]["properties"])
    note_required = set(RESPONSE_SCHEMA["properties"]["notes"]["items"]["required"])
    for index, note in enumerate(notes):
        if not isinstance(note, dict):
            raise ValueError(f"editor_review.notes[{index}] must be an object")
        unknown_note = sorted(set(note) - note_allowed)
        if unknown_note:
            raise ValueError(f"editor_review.notes[{index}] has unknown keys: {unknown_note}")
        missing_note = sorted(note_required - set(note))
        if missing_note:
            raise ValueError(f"editor_review.notes[{index}] missing required keys: {missing_note}")
        if not isinstance(note.get("clip_order"), int):
            raise ValueError(f"editor_review.notes[{index}].clip_order must be an integer")
        clip_uuid = note.get("clip_uuid")
        if not isinstance(clip_uuid, str) or re.fullmatch(r"[0-9a-f]{8}", clip_uuid) is None:
            raise ValueError(f"editor_review.notes[{index}].clip_uuid must be 8 lowercase hex characters")
        for key in ("observation", "brief_impact"):
            if not isinstance(note.get(key), str):
                raise ValueError(f"editor_review.notes[{index}].{key} must be a string")
        if note.get("action") not in EDITOR_ACTIONS:
            raise ValueError(f"editor_review.notes[{index}].action is invalid")
        detail = note.get("action_detail")
        if detail is not None and not isinstance(detail, dict):
            raise ValueError(f"editor_review.notes[{index}].action_detail must be an object or null")
        if note.get("priority") not in EDITOR_PRIORITIES:
            raise ValueError(f"editor_review.notes[{index}].priority is invalid")
        candidate_pool_id = note.get("candidate_pool_id")
        if candidate_pool_id is not None and not isinstance(candidate_pool_id, str):
            raise ValueError(f"editor_review.notes[{index}].candidate_pool_id must be a string or null")
    if payload.get("verdict") not in {"ship", "iterate", "rework"}:
        raise ValueError("editor_review.verdict is invalid")
    ship_confidence = payload.get("ship_confidence")
    if not isinstance(ship_confidence, (int, float)) or not 0 <= float(ship_confidence) <= 1:
        raise ValueError("editor_review.ship_confidence must be a number between 0 and 1")
    if arrangement is not None:
        _validate_note_uuid_references(notes, arrangement)


def _probe_duration(
    hype_mp4: Path,
    *,
    ffprobe_runner: Any = subprocess.run,
) -> float:
    result = ffprobe_runner(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(hype_mp4),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(str(result.stdout).strip())


def sample_frames(
    hype_mp4: Path,
    cache_dir: Path,
    *,
    cadence_sec: float = 1.5,
    max_frames: int = 50,
    ffmpeg_runner: Any = subprocess.run,
    ffprobe_runner: Any = subprocess.run,
) -> list[Path]:
    """Sample review frames from the rendered artifact without copying the video."""

    hype_mp4 = Path(hype_mp4)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    duration_sec = _probe_duration(hype_mp4, ffprobe_runner=ffprobe_runner)
    count = min(int(max_frames), int(duration_sec // float(cadence_sec)) + 1)
    frame_pattern = cache_dir / "frame_%03d.jpg"
    ffmpeg_runner(
        [
            "ffmpeg",
            "-ss",
            "0",
            "-i",
            str(hype_mp4),
            "-vf",
            f"fps=1/{float(cadence_sec):g}",
            "-frames:v",
            str(count),
            str(frame_pattern),
            "-hide_banner",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(cache_dir.glob("frame_*.jpg"))


def _model_dump_or_dict(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return dict(response.model_dump())
    if isinstance(response, dict):
        return dict(response)
    return dict(response)


def transcribe_hype_audio(
    hype_mp4: Path,
    cache_dir: Path,
    *,
    openai_client: Any,
    model: str = "whisper-1",
    ffmpeg_runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Extract audio from hype.mp4 and transcribe that rendered artifact."""

    hype_mp4 = Path(hype_mp4)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    audio_path = cache_dir / "hype_audio.mp3"
    ffmpeg_runner(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(hype_mp4),
            "-vn",
            "-acodec",
            "libmp3lame",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    with audio_path.open("rb") as handle:
        response = openai_client.audio.transcriptions.create(
            model=model,
            file=handle,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    data = _model_dump_or_dict(response)
    segments = [
        {
            "start": float(segment.get("start", 0.0)),
            "end": float(segment.get("end", 0.0)),
            "text": str(segment.get("text", "")).strip(),
        }
        for segment in list(data.get("segments") or [])
        if isinstance(segment, dict)
    ]
    return {"text": str(data.get("text", "")).strip(), "segments": segments}


def _note_key_set(value: Any) -> set[tuple[str, str]]:
    notes = value.get("notes") if isinstance(value, dict) else value
    if not isinstance(notes, list):
        return set()
    result: set[tuple[str, str]] = set()
    for note in notes:
        if not isinstance(note, dict):
            continue
        clip_uuid = note.get("clip_uuid")
        action = note.get("action")
        if (
            isinstance(clip_uuid, str)
            and re.fullmatch(r"[0-9a-f]{8}", clip_uuid) is not None
            and isinstance(action, str)
        ):
            result.add((clip_uuid, action))
    return result


def notes_overlap_ratio(prev: Any, curr: Any) -> float:
    prev_keys = _note_key_set(prev)
    curr_keys = _note_key_set(curr)
    denominator = max(len(prev_keys), len(curr_keys))
    if denominator == 0:
        return 0.0
    return len(prev_keys & curr_keys) / denominator


def plan_next_action(review: dict[str, Any]) -> str:
    if review.get("verdict") == "ship":
        return "ship"
    notes = review.get("notes")
    if not isinstance(notes, list):
        notes = []
    actionable = [note for note in notes if isinstance(note, dict) and note.get("action") != "accept"]
    if all(note.get("action") == "micro-fix" for note in actionable):
        return "micro-fix"
    return "rework"


def build_openai_client(env_file: Path | None = None) -> Any:
    from openai import OpenAI

    return OpenAI(api_key=load_api_key(env_file))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _brief_text(brief_dir: Path, arrangement: dict[str, Any]) -> str:
    brief_path = brief_dir / "brief.txt"
    if brief_path.is_file():
        return brief_path.read_text(encoding="utf-8").strip()
    text = arrangement.get("brief_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise ValueError(f"brief text not found in {brief_path} or arrangement.brief_text")


def _clip_pool_and_role(clip: dict[str, Any]) -> tuple[str, str]:
    audio_source = clip.get("audio_source")
    visual_source = clip.get("visual_source")
    pool_id = "none"
    role = "primary"
    if isinstance(audio_source, dict) and isinstance(audio_source.get("pool_id"), str):
        pool_id = audio_source["pool_id"]
    if isinstance(visual_source, dict):
        if pool_id == "none" and isinstance(visual_source.get("pool_id"), str):
            pool_id = visual_source["pool_id"]
        if isinstance(visual_source.get("role"), str):
            role = visual_source["role"]
    return pool_id, role


def arrangement_summary(arrangement: dict[str, Any]) -> str:
    lines: list[str] = []
    for clip in sorted(arrangement.get("clips", []), key=lambda item: int(item.get("order", 0)) if isinstance(item, dict) else 0):
        if not isinstance(clip, dict):
            continue
        pool_id, role = _clip_pool_and_role(clip)
        rationale = str(clip.get("rationale", "")).replace("\n", " ").strip()
        lines.append(
            f"[{clip['order']}] uuid={clip.get('uuid')} pool={pool_id} role={role} rationale={rationale[:80]}"
        )
    return "\n".join(lines)


def inspect_cut_text(brief_dir: Path, *, runner: Any | None = None) -> str:
    if runner is None:
        runner = subprocess.run
    result = runner(
        [sys.executable, str(REPO_ROOT / "inspect_cut.py"), str(brief_dir), "--no-color"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = str(result.stderr or result.stdout or "").strip()
        return f"! inspect_cut failed: {stderr}"
    return str(result.stdout or "").strip()


def _transcript_text(transcript: dict[str, Any]) -> str:
    segments = transcript.get("segments")
    if not isinstance(segments, list) or not segments:
        return str(transcript.get("text", "")).strip()
    lines = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))
        text = str(segment.get("text", "")).strip()
        lines.append(f"[{start:.2f}-{end:.2f}] {text}")
    return "\n".join(lines)


def build_system_prompt(
    *,
    brief_text: str,
    arrangement_text: str,
    refine_report: dict[str, Any],
    inspect_text: str,
    quality_zones: dict[str, Any],
    pool_text: str,
    transcript: dict[str, Any],
) -> str:
    return "\n\n".join(
        [
            "You are a senior short-form video editor reviewing the rendered hype.mp4 against the brief. "
            "Use the artifact evidence first. Return only structured editor_review JSON. "
            "Prefer minimal downstream actions: accept, micro-fix, swap, reorder, insert-stinger, or needs-better-pool-entry.",
            "Every note must include `clip_uuid` copied verbatim from the arrangement clip you reference.",
            f"BRIEF:\n{brief_text}",
            f"ARRANGEMENT SUMMARY:\n{arrangement_text}",
            f"REFINE JSON:\n{json.dumps(refine_report, indent=2, sort_keys=True)}",
            f"INSPECT CUT:\n{inspect_text}",
            f"QUALITY ZONES:\n{json.dumps(quality_zones, indent=2, sort_keys=True)}",
            f"POOL DIGEST:\n{pool_text}",
            f"RENDERED AUDIO TRANSCRIPT:\n{_transcript_text(transcript)}",
        ]
    )


def build_vision_messages(
    *,
    frames: list[Path],
    cadence_sec: float,
    summary_text: str,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Review these sampled frames from the rendered hype.mp4 together with the system evidence. "
                "Identify only material issues that affect the brief, pacing, clarity, quality, or ordering.\n\n"
                f"{summary_text}"
            ),
        }
    ]
    for index, frame in enumerate(frames):
        content.append({"type": "text", "text": f"(t={index * float(cadence_sec):.1f}s)"})
        content.append({"type": "image", "source": {"type": "path", "path": str(frame)}})
    return [{"role": "user", "content": content}]


def _validated_review(response: dict[str, Any], arrangement: dict[str, Any], *, iteration: int) -> dict[str, Any]:
    payload = dict(response)
    payload["iteration"] = int(iteration)
    _validate_review_payload_shape(payload, arrangement)
    _validate_editor_notes(payload, arrangement)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review a rendered hype.mp4 against its brief.")
    parser.add_argument("--brief-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-frames", type=int, default=50)
    parser.add_argument("--cadence-sec", type=float, default=1.5)
    parser.add_argument("--skip-llm", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 1 <= int(args.iteration) <= 2:
        parser.error("--iteration must be 1 or 2")

    brief_dir = args.brief_dir.resolve()
    run_dir = args.run_dir.resolve()
    out_dir = args.out.resolve()
    hype_mp4 = brief_dir / "hype.mp4"
    arrangement = load_arrangement(brief_dir / "arrangement.json", assign_missing_uuids=True)
    refine_report = _read_json(brief_dir / "refine.json")
    quality_zones_path = run_dir / "quality_zones.json"
    quality_zones = _read_json(quality_zones_path) if quality_zones_path.is_file() else {}
    _ = load_metadata(brief_dir / "hype.metadata.json")
    pool = load_pool(run_dir / "pool.json")
    brief = _brief_text(brief_dir, arrangement)

    review_cache = out_dir / ".editor_review_cache" / f"iteration_{int(args.iteration)}"
    frames = sample_frames(hype_mp4, review_cache / "frames", cadence_sec=args.cadence_sec, max_frames=args.max_frames)
    if args.skip_llm:
        transcript = {"text": "", "segments": []}
        response = {"iteration": int(args.iteration), "notes": [], "verdict": "ship", "ship_confidence": 1.0}
    else:
        transcript = transcribe_hype_audio(
            hype_mp4,
            review_cache / "audio",
            openai_client=build_openai_client(args.env_file),
        )
        arrangement_text = arrangement_summary(arrangement)
        inspect_text = inspect_cut_text(brief_dir)
        system_prompt = build_system_prompt(
            brief_text=brief,
            arrangement_text=arrangement_text,
            refine_report=refine_report,
            inspect_text=inspect_text,
            quality_zones=quality_zones,
            pool_text=pool_digest(pool),
            transcript=transcript,
        )
        messages = build_vision_messages(
            frames=frames,
            cadence_sec=args.cadence_sec,
            summary_text=(
                "Return editor_review JSON with clip_order and clip_uuid references matching arrangement order. "
                "Every note must include clip_uuid copied verbatim from the arrangement clip you reference. "
                "For swap actions include candidate_pool_id when a replacement exists."
            ),
        )
        response = build_claude_client(args.env_file).complete_json(
            model=args.model,
            system=system_prompt,
            messages=messages,
            response_schema=RESPONSE_SCHEMA,
            max_tokens=4000,
        )

    review = _validated_review(response, arrangement, iteration=int(args.iteration))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "editor_review.json"
    out_path.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
