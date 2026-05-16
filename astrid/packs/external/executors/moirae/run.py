"""Runtime entrypoint for external.moirae."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Moirae against a screenplay.")
    parser.add_argument("screenplay", type=Path)
    parser.add_argument("-o", "--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = Path(args.output)
    if output.suffix == "":
        output = output.with_suffix(".mp4")
    rc = subprocess.run([sys.executable, "-m", "moirae", str(args.screenplay), "-o", str(output)]).returncode
    if rc == 0 and output != Path(args.output) and not Path(args.output).exists():
        Path(args.output).symlink_to(output.name)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
