#!/usr/bin/env python3
"""Unified dispatcher for ArtAgents understanding executors.

`builtin.understand` selects an underlying modality executor (audio, visual,
or video) via `--mode` and forwards the remaining argv unchanged. This is
deliberately a thin executor — not an orchestrator — because it wraps exactly
one executor call with a switch.
"""

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
        description="Dispatch to audio, image/visual, or video understanding executors.",
        epilog=(
            "Examples: understand --mode image --image frame.jpg --query 'What is here?'; "
            "understand --mode audio --audio quote.wav; "
            "understand --mode video --video source.mp4 --at 01:20"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=sorted(ALIASES),
        required=True,
        help="Understanding modality. All other arguments are forwarded to the selected executor.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args, forwarded = build_parser().parse_known_args(argv)
    return _resolve_alias(args.mode)(forwarded)


def _resolve_alias(mode: str) -> Callable[[list[str]], int]:
    target = ALIASES[mode]
    if callable(target):
        return target
    module_name, function_name = target.split(":", 1)
    return getattr(import_module(module_name), function_name)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
