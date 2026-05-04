#!/usr/bin/env python3
"""Query a video-native Gemini model against source video windows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from artagents.utilities.llm_clients import build_gemini_client


MODEL_PRESETS = {
    "fast": "gemini-2.5-flash",
    "best": "gemini-2.5-pro",
}
DEFAULT_MODE = "fast"
DEFAULT_QUERY = """Watch this video as editorial evidence, using both picture and sound.

Return compact JSON with:
- summary: what happens in the clip
- visual_read: people, setting, framing, action, text, graphics, cuts, camera motion
- audio_read: speech delivery, music/SFX, applause/laughter, room tone, noise, sync issues
- edit_value: why this moment is or is not useful in a cut
- highlight_score: 0-10
- energy: 0-10
- pacing: slow/steady/fast/chaotic
- production_quality: visual/audio quality problems, bad cuts, focus/exposure, clipping, echo
- boundary_notes: suggested clean in/out points relative to this window
- cautions: uncertainty or details that need transcript/frame/audio follow-up
"""
RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "visual_read": {"type": "string"},
        "audio_read": {"type": "string"},
        "edit_value": {"type": "string"},
        "highlight_score": {"type": "number"},
        "energy": {"type": "number"},
        "pacing": {"type": "string"},
        "production_quality": {"type": "string"},
        "boundary_notes": {"type": "string"},
        "cautions": {"type": "string"},
    },
    "required": [
        "summary",
        "visual_read",
        "audio_read",
        "edit_value",
        "highlight_score",
        "energy",
        "pacing",
        "production_quality",
        "boundary_notes",
        "cautions",
    ],
}


def _die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _parse_timestamp(value: str) -> float:
    raw = value.strip()
    if not raw:
        _die("empty timestamp")
    if ":" not in raw:
        return float(raw)
    parts = [float(part) for part in raw.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    _die(f"invalid timestamp: {value}")
    return 0.0


def _format_time(seconds: float) -> str:
    whole = int(seconds)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _parse_times(values: list[str] | None) -> list[float]:
    times: list[float] = []
    for value in values or []:
        for part in value.split(","):
            if part.strip():
                times.append(_parse_timestamp(part))
    return times


def _probe_duration(media_path: Path) -> float:
    return float(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ]
        ).stdout.strip()
    )


def _window_plan(args: argparse.Namespace, duration_sec: float) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    if args.start is not None or args.end is not None:
        start = 0.0 if args.start is None else _parse_timestamp(args.start)
        end = duration_sec if args.end is None else _parse_timestamp(args.end)
        if end <= start:
            _die("--end must be after --start")
        windows.append({"index": 1, "start": max(0.0, start), "end": min(duration_sec, end), "label": "range"})
    for seconds in _parse_times(args.at):
        half = args.window_sec / 2.0
        start = max(0.0, seconds - half)
        end = min(duration_sec, seconds + half)
        if end > start:
            windows.append({"index": len(windows) + 1, "start": start, "end": end, "label": f"around {_format_time(seconds)}"})
    if not windows:
        start = 0.0
        while start < duration_sec - 1e-6 and len(windows) < args.max_chunks:
            end = min(duration_sec, start + args.chunk_sec)
            windows.append({"index": len(windows) + 1, "start": start, "end": end, "label": "auto"})
            start = end
    if len(windows) > args.max_chunks:
        _die(f"too many video windows: {len(windows)} > {args.max_chunks}")
    return [
        {
            **window,
            "start": round(float(window["start"]), 3),
            "end": round(float(window["end"]), 3),
            "duration": round(float(window["end"]) - float(window["start"]), 3),
        }
        for window in windows
    ]


def _extract_window(source: Path, window: dict[str, Any], out_dir: Path, *, force: bool, max_width: int) -> Path:
    clips_dir = out_dir / "video-windows"
    clips_dir.mkdir(parents=True, exist_ok=True)
    start_ms = int(float(window["start"]) * 1000)
    end_ms = int(float(window["end"]) * 1000)
    path = clips_dir / f"window_{int(window['index']):03d}_{start_ms:09d}_{end_ms:09d}.mp4"
    if path.exists() and not force:
        return path
    vf = f"scale='min({max_width},iw)':-2" if max_width > 0 else "scale=iw:ih"
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{float(window['start']):.3f}",
            "-to",
            f"{float(window['end']):.3f}",
            "-i",
            str(source),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "26",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            str(path),
        ]
    )
    return path


def run(args: argparse.Namespace) -> int:
    video_source = args.video.expanduser()
    if not video_source.is_file():
        _die(f"video not found: {video_source}")
    if args.max_chunks < 1:
        _die("--max-chunks must be >= 1")
    if args.chunk_sec <= 0 or args.window_sec <= 0:
        _die("--chunk-sec and --window-sec must be > 0")
    if args.max_width < 0:
        _die("--max-width must be >= 0")

    out_dir = args.out_dir.expanduser()
    duration_sec = _probe_duration(video_source)
    windows = _window_plan(args, duration_sec)
    extracted = []
    for window in windows:
        path = _extract_window(video_source, window, out_dir, force=args.force, max_width=args.max_width)
        extracted.append({**window, "path": str(path), "source": str(video_source)})

    primary_model = args.model or MODEL_PRESETS[args.mode]
    models = [primary_model, *args.compare_model]
    preview = {
        "provider": "gemini",
        "models": models,
        "source": str(video_source),
        "source_kind": "video",
        "duration_sec": round(duration_sec, 3),
        "query": args.query,
        "windows": extracted,
        "philosophy": "Direct video understanding is treated as synchronized sight-and-sound evidence. Use visual_understand.py for cheap frame/contact-sheet reads, audio_understand.py for isolated listening judgment, and transcribe.py for exact words.",
    }
    if args.dry_run:
        print(json.dumps(preview, indent=2))
        return 0

    client = build_gemini_client(args.env_file)
    results: list[dict[str, Any]] = []
    for model in models:
        for window in extracted:
            video_path = Path(window["path"])
            prompt = (
                f"{args.query}\n\n"
                f"Clip label: {window['label']}. "
                f"Window index {window['index']} covers source-relative {window['start']}s to {window['end']}s. "
                "When giving boundary notes, describe offsets relative to this clip/window, not absolute source timestamps."
            )
            print(f"querying={model} window={window['index']} video={video_path}", file=sys.stderr)
            started = time.time()
            try:
                response = client.describe_video(
                    model=model,
                    video_path=video_path,
                    prompt=prompt,
                    response_schema=RESPONSE_SCHEMA,
                )
                result = {
                    "model": model,
                    "window": window,
                    "status": "ok",
                    "elapsed_sec": round(time.time() - started, 2),
                    "answer": response,
                }
            except Exception as exc:
                result = {
                    "model": model,
                    "window": window,
                    "status": "error",
                    "elapsed_sec": round(time.time() - started, 2),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            results.append(result)

    output = {**preview, "results": results}
    text = json.dumps(output, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote={args.out}", file=sys.stderr)
    return 0 if all(result["status"] == "ok" for result in results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ask a video-native Gemini model about source video windows.",
        epilog="Use this when the editorial question depends on synchronized picture and sound. Use visual_understand.py for cheap frame sheets and audio_understand.py for isolated delivery/sound judgment.",
    )
    add = parser.add_argument
    add("--query", default=DEFAULT_QUERY, help="Question/instruction for the model. Defaults to an editorial video-understanding JSON rubric.")
    add("--video", type=Path, required=True, help="Video file to inspect.")
    add("--at", action="append", help="Center timestamp(s), comma-separated or repeated. Supports seconds, MM:SS, HH:MM:SS.")
    add("--start", help="Optional range start timestamp.")
    add("--end", help="Optional range end timestamp.")
    add("--window-sec", type=float, default=20.0, help="Window length around each --at timestamp.")
    add("--chunk-sec", type=float, default=30.0, help="Auto chunk length when --at/--start are omitted.")
    add("--max-chunks", type=int, default=8)
    add("--max-width", type=int, default=960, help="Downscale extracted clips to this width before upload. 0 keeps source width.")
    add("--mode", choices=sorted(MODEL_PRESETS), default=DEFAULT_MODE, help="fast uses Gemini Flash; best uses Gemini Pro.")
    add("--model", help="Explicit Gemini model override.")
    add("--compare-model", action="append", default=[], help="Additional Gemini model to query against the same windows.")
    add("--out-dir", type=Path, default=Path("runs/video-understanding"))
    add("--out", type=Path, help="Optional JSON result path.")
    add("--env-file", type=Path)
    add("--timeout", type=int, default=300, help="Reserved for parity with other understanding tools.")
    add("--force", action="store_true")
    add("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
