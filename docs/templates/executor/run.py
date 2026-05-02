#!/usr/bin/env python3
"""Example executor runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the example executor.")
    parser.add_argument("--input", type=Path, required=True, help="Input artifact.")
    parser.add_argument("--out", type=Path, required=True, help="Output JSON path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"input": str(args.input), "ok": True}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"example: wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
