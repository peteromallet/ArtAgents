#!/usr/bin/env python3
"""Unified dispatcher for ArtAgents understanding tools."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from importlib import import_module
import sys


ALIASES: dict[str, str | Callable[[list[str]], int]] = {
    "audio": "artagents.executors.audio_understand.run:main",
    "image": "artagents.executors.visual_understand.run:main",
    "visual": "artagents.executors.visual_understand.run:main",
    "video": "artagents.executors.video_understand.run:main",
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
    return _resolve_alias(args.kind)(args.args)


def _resolve_alias(kind: str) -> Callable[[list[str]], int]:
    target = ALIASES[kind]
    if callable(target):
        return target
    module_name, function_name = target.split(":", 1)
    return getattr(import_module(module_name), function_name)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
