#!/usr/bin/env python3
"""seinfeld.repo_setup — idempotent ai-toolkit submodule initializer.

If ``astrid/packs/seinfeld/ai_toolkit/upstream/.git`` already exists,
exits 0 with ``{status: "already_initialized"}``.  Otherwise runs
``git submodule add`` + ``git checkout <PINNED_SHA>`` and exits 0.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Pinned SHA — single source of truth.  HEAD of ostris/ai-toolkit main
# as of 2026-05-12; confirmed LTX 2.3 support.
PINNED_SHA = "f38de2a2fedfafa4bf298806d1efcabb4a357cbc"

SUBMODULE_URL = "https://github.com/ostris/ai-toolkit.git"
SUBMODULE_PATH = "astrid/packs/seinfeld/ai_toolkit/upstream"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _repo_root() -> Path:
    """Return the git worktree root by walking up from this file."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git rev-parse failed — not inside a git working tree? "
            f"stderr: {result.stderr.strip()}"
        )
    return Path(result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Idempotent ai-toolkit submodule initializer."
    )
    parser.add_argument(
        "--produces-dir", type=Path, required=True,
        help="Produces output directory (framework provides via {out}/produces).",
    )
    args = parser.parse_args(argv)
    produces_dir: Path = args.produces_dir
    produces_dir.mkdir(parents=True, exist_ok=True)

    root = _repo_root()
    submodule_path = root / SUBMODULE_PATH

    # Idempotency: already initialized?
    if (submodule_path / ".git").exists():
        result = {"status": "already_initialized", "sha": PINNED_SHA}
        _write_json(produces_dir / "setup_result.json", result)
        print(f"repo_setup: ai-toolkit submodule already initialized at {submodule_path}")
        return 0

    # ── git submodule add ──────────────────────────────────────────
    print(f"repo_setup: adding submodule {SUBMODULE_URL} → {SUBMODULE_PATH}")
    result = subprocess.run(
        ["git", "submodule", "add", SUBMODULE_URL, SUBMODULE_PATH],
        capture_output=True, text=True, cwd=root,
    )
    if result.returncode != 0:
        print(
            f"ERROR: git submodule add failed:\n{result.stderr}",
            file=sys.stderr,
        )
        return 1

    # ── git checkout pinned SHA ────────────────────────────────────
    print(f"repo_setup: checking out pinned SHA {PINNED_SHA}")
    result = subprocess.run(
        ["git", "checkout", PINNED_SHA],
        capture_output=True, text=True, cwd=submodule_path,
    )
    if result.returncode != 0:
        print(
            f"ERROR: git checkout {PINNED_SHA} failed:\n{result.stderr}",
            file=sys.stderr,
        )
        return 2

    # ── git add .gitmodules + submodule ────────────────────────────
    subprocess.run(
        ["git", "add", ".gitmodules", SUBMODULE_PATH],
        capture_output=True, text=True, cwd=root,
    )

    submodule_result = {"status": "initialized", "sha": PINNED_SHA}
    _write_json(produces_dir / "setup_result.json", submodule_result)
    print(f"repo_setup: ai-toolkit initialized at {submodule_path} @ {PINNED_SHA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())