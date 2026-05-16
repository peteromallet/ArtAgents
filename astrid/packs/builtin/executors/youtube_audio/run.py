"""Download a YouTube video's audio (MP3) or video (MP4) — via search or direct URL."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _die(msg: str, code: int = 2) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--query", help="YouTube search query; the top hit is used.")
    src.add_argument("--url", help="Direct YouTube URL; skips search.")
    parser.add_argument(
        "--mode",
        choices=("audio", "video"),
        default="audio",
        help="audio: extract to MP3 (default, legacy behaviour). video: download MP4 without audio extraction.",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output path. Extension is appended to match --mode if missing.",
    )
    parser.add_argument(
        "--audio-format",
        default="mp3",
        help="Audio format passed to yt-dlp --audio-format (audio mode only).",
    )
    parser.add_argument(
        "--audio-quality",
        default="0",
        help="yt-dlp --audio-quality (audio mode only, 0 = best for VBR).",
    )
    parser.add_argument(
        "--video-format",
        default="bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        help="yt-dlp -f selector (video mode only). Default prefers mp4 but falls back to merging best A+V.",
    )
    parser.add_argument(
        "--merge-output-format",
        default="mp4",
        help="yt-dlp --merge-output-format (video mode only); ensures final container is mp4.",
    )
    args = parser.parse_args(argv)

    if not shutil.which("yt-dlp"):
        return _die("yt-dlp not found on PATH. Install via `pip install yt-dlp`.")
    if args.mode == "audio" and not shutil.which("ffmpeg"):
        return _die("ffmpeg not found on PATH. yt-dlp needs it to extract audio.")

    out = args.out
    default_ext = args.audio_format if args.mode == "audio" else "mp4"
    if out.suffix == "":
        out = out.with_suffix(f".{default_ext}")
    out.parent.mkdir(parents=True, exist_ok=True)

    output_template = str(out.with_suffix(f".%(ext)s"))
    target = args.url if args.url else f"ytsearch1:{args.query}"

    cmd = ["yt-dlp", "--no-warnings", "--output", output_template]
    if args.mode == "audio":
        cmd += [
            "--extract-audio",
            f"--audio-format={args.audio_format}",
            f"--audio-quality={args.audio_quality}",
        ]
    else:
        cmd += ["-f", args.video_format, "--merge-output-format", args.merge_output_format]
    cmd.append(target)

    print(f"[youtube_audio] {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        return _die(f"yt-dlp failed (exit {proc.returncode})", proc.returncode)

    if not out.exists():
        return _die(
            f"yt-dlp returned success but expected output {out} is missing. "
            "stdout:\n" + proc.stdout + "\nstderr:\n" + proc.stderr,
            3,
        )

    print(f"Downloaded: {out} ({out.stat().st_size:,} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
