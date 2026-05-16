#!/usr/bin/env python3
"""seinfeld.lora_register — copy chosen LoRA and emit registered_lora.json."""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import shutil
import sys
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Register chosen seinfeld LoRA.")
    p.add_argument("--chosen-checkpoint", type=Path, required=True)
    p.add_argument("--lora-source", type=Path, required=True)
    p.add_argument("--staged-config", type=Path, required=True)
    p.add_argument("--vocabulary", type=Path, required=True)
    p.add_argument("--produces-dir", type=Path, required=True)
    p.add_argument("--base-model", default="ltx-2.3")
    p.add_argument("--lora-id", default="seinfeld-scene-v1")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    produces = args.produces_dir
    registered_dir = produces / "registered"
    registered_dir.mkdir(parents=True, exist_ok=True)

    chosen = json.loads(args.chosen_checkpoint.read_text(encoding="utf-8"))
    step = int(chosen.get("step", chosen.get("checkpoint_step", -1)))
    notes = str(chosen.get("notes", chosen.get("human_pick_notes", "")))

    if not args.lora_source.exists():
        print(f"ERROR: lora source not found: {args.lora_source}", file=sys.stderr)
        return 2

    dst = registered_dir / f"{args.lora_id}.safetensors"
    shutil.copy2(args.lora_source, dst)

    record = {
        "lora_id": args.lora_id,
        "checkpoint_step": step,
        "lora_file": str(dst.resolve()),
        "config_used": str(args.staged_config.resolve()),
        "base_model": args.base_model,
        "vocabulary_hash": _sha256(args.vocabulary),
        "trained_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "human_pick_notes": notes,
    }
    out_path = produces / "registered_lora.json"
    out_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"lora_register: wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
