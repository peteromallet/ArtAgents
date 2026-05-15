"""media.make_trailer — orchestrator runtime entrypoint.

Coordinates asset ingestion and assembly into a trailer.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Coordinate asset ingestion and assembly.",
    )
    parser.add_argument("--out", type=Path, help="Output directory for the trailer.")
    parser.add_argument("--brief", type=Path, help="Brief describing the trailer.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir: Path = args.out or Path.cwd() / "trailer_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    brief: Path | None = args.brief
    print(f"make_trailer: out={out_dir} brief={brief}")

    # Stub: write a trailer manifest
    manifest = out_dir / "trailer_manifest.txt"
    lines = ["# Trailer Build Plan"]
    if brief and brief.is_file():
        brief_text = brief.read_text().strip()[:200]
        lines.append(f"Brief: {brief_text}")
    lines.append("Scenes: [project-title-card, ...]")
    manifest.write_text("\n".join(lines) + "\n")
    print(f"make_trailer: wrote manifest to {manifest}")

    print("make_trailer: done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
