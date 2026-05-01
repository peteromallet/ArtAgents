#!/usr/bin/env python3
"""Unified dispatcher for ArtAgents understanding tools."""

from __future__ import annotations

import argparse
import sys

from . import audio_understand, video_understand, visual_understand


ALIASES = {
    "audio": audio_understand.main,
    "image": visual_understand.main,
    "visual": visual_understand.main,
    "video": video_understand.main,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dispatch to audio, image/visual, or video understanding tools.",
        epilog=(
            "Examples: understand.py image --image frame.jpg --query 'What is here?'; "
            "understand.py audio --audio quote.wav; "
            "understand.py video --video source.mp4 --at 01:20"
        ),
    )
    parser.add_argument("kind", choices=sorted(ALIASES), help="Understanding modality.")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to the selected tool.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return ALIASES[args.kind](args.args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
