#!/usr/bin/env python3
"""Seinfeld lora_train orchestrator — skeleton, Phase 2 work.

See ./STAGE.md for the step list and dependencies.
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Train a Seinfeld LoRA on LTX 2.3 via ai-toolkit on RunPod.")
    p.add_argument("--manifest", required=True, help="Path to dataset_build manifest.json.")
    p.add_argument("--vocabulary", required=True, help="Path to vocabulary.yaml.")
    p.add_argument("--base-model", default="ltx-2.3")
    p.add_argument("--rank", type=int, default=32)
    p.add_argument("--steps", type=int, default=4000)
    p.add_argument("--gpu", default="a100-80g")
    p.add_argument("--out", required=True)
    p.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print("seinfeld.lora_train is a SKELETON — Phase 2 work. See STAGE.md.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
