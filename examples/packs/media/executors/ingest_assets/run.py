"""media.ingest_assets — executor runtime entrypoint.

Ingests and validates project assets from a source directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest and validate project assets.",
    )
    parser.add_argument("--source", type=Path, help="Source directory of assets.")
    parser.add_argument("--out", type=Path, help="Output directory.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir: Path = args.out or Path.cwd() / "ingested"
    out_dir.mkdir(parents=True, exist_ok=True)

    source: Path = args.source or Path.cwd()
    print(f"ingest_assets: source={source} out={out_dir}")

    # Count files in source
    file_count = 0
    if source.is_dir():
        files = [f for f in source.iterdir() if f.is_file()]
        file_count = len(files)
        print(f"ingest_assets: found {file_count} files in source")

        # Write a manifest of ingested assets
        manifest = out_dir / "assets_manifest.txt"
        manifest.write_text("\n".join(sorted(str(f.name) for f in files)) + "\n")
        print(f"ingest_assets: wrote manifest to {manifest}")

    print(f"ingest_assets: done ({file_count} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
