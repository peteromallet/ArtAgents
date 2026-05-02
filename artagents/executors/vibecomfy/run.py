"""Runtime entrypoint for external.vibecomfy.*."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run VibeComfy workflow commands.")
    parser.add_argument("command", choices=("run", "validate"))
    parser.add_argument("workflow", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return subprocess.run([sys.executable, "-m", "vibecomfy.cli", args.command, str(args.workflow)]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
