#!/usr/bin/env python3
"""Onboarding rite: summon a portrait of the maker and open it."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from artagents.executors.generate_image.run import main as generate_image_main


PROMPT = (
    "An illuminated medieval manuscript page depicting Saint Peter of Banodoco, "
    "patron of file-based pipelines, haloed in glowing unix prompts, quill in "
    "hand inscribing ffmpeg incantations. Tiny familiar spirits labelled REIGH, "
    "LOTA, and MOIRAE peer over his shoulders. Gold leaf, vellum, Celtic "
    "knotwork border."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the first rite.")
    parser.add_argument("--out", type=Path, default=Path("runs/first-rite"))
    parser.add_argument("--no-open", action="store_true", help="Skip opening the rendered image.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without calling the API.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    prompt_file = out_dir / "prompt.txt"
    prompt_file.write_text(PROMPT + "\n", encoding="utf-8")
    print(f"Wrote {prompt_file}")

    images_dir = out_dir / "images"
    manifest = out_dir / "manifest.json"
    gen_argv = [
        "--prompts-file", str(prompt_file),
        "--out-dir", str(images_dir),
        "--manifest", str(manifest),
        "--force",
    ]
    if args.dry_run:
        gen_argv.append("--dry-run")

    rc = generate_image_main(gen_argv)
    if rc != 0:
        return rc

    if args.dry_run or args.no_open:
        return 0

    rendered = sorted(images_dir.glob("*.png")) + sorted(images_dir.glob("*.jpeg")) + sorted(images_dir.glob("*.webp"))
    if not rendered:
        print("No image was rendered; nothing to open.", file=sys.stderr)
        return 0

    target = rendered[0]
    print(f"Opening {target}")
    subprocess.run(["open", str(target)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
