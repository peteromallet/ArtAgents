"""Search YouTube for a query and download the top hit's audio as MP3."""

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
    parser.add_argument("--query", required=True, help="YouTube search query.")
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output path. .mp3 extension is appended if missing.",
    )
    parser.add_argument(
        "--audio-format",
        default="mp3",
        help="Audio format passed to yt-dlp --audio-format.",
    )
    parser.add_argument(
        "--audio-quality",
        default="0",
        help="yt-dlp --audio-quality (0 = best for VBR).",
    )
    args = parser.parse_args(argv)

    if not shutil.which("yt-dlp"):
        return _die("yt-dlp not found on PATH. Install via `pip install yt-dlp`.")
    if not shutil.which("ffmpeg"):
        return _die("ffmpeg not found on PATH. yt-dlp needs it to extract audio.")

    out = args.out
    if out.suffix == "":
        out = out.with_suffix(f".{args.audio_format}")
    out.parent.mkdir(parents=True, exist_ok=True)

    # yt-dlp's --output template controls the final filename. We want the
    # extension to match args.audio_format so the post-processed file lands
    # at the path our manifest declares as the output.
    output_template = str(out.with_suffix(f".%(ext)s"))

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--extract-audio",
        f"--audio-format={args.audio_format}",
        f"--audio-quality={args.audio_quality}",
        "--output",
        output_template,
        f"ytsearch1:{args.query}",
    ]
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
