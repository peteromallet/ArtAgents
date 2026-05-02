#!/usr/bin/env python3
"""Example orchestrator runtime."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the example orchestrator.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned work without running it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run:
        print("example orchestrator: would run child executors")
        return 0
    print("example orchestrator: run child executors here")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
