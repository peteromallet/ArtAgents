#!/usr/bin/env python3
"""Migrate Sprint 2 step directories to versioned paths (v1/).

Usage:
  scripts/migrations/sprint-3/migrate_step_paths.py --dry-run   # default: preview
  scripts/migrations/sprint-3/migrate_step_paths.py --apply      # commit changes

Walks ``runs/*/steps/<id>/*`` and renames to ``runs/*/steps/<id>/v1/*``.
Idempotent: directories that already have a ``v<N>/`` child are skipped.
Empty workspace (no step dirs) exits 0 cleanly.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECTS_ROOT_DEFAULT = os.path.expanduser("~/Documents/reigh-workspace/astrid-projects")


def _has_versioned_child(step_dir: Path) -> bool:
    """True if this step_dir already has a v<N>/ child directory."""
    if not step_dir.is_dir():
        return False
    for child in step_dir.iterdir():
        if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit():
            return True
    return False


def _find_step_dirs_to_migrate(projects_root: Path) -> list[tuple[Path, Path]]:
    """Return [(steps_dir_containing_dirs, dir_name), ...] to migrate.

    Each item is a directory directly under steps/<id>/ that is NOT already
    versioned (i.e., not named v<N>/) and has no existing v<N>/ sibling.
    """
    to_migrate: list[tuple[Path, Path]] = []
    if not projects_root.exists():
        return to_migrate

    for steps_parent in projects_root.glob("*/runs/*/steps"):
        if not steps_parent.is_dir():
            continue
        for step_id_dir in sorted(steps_parent.iterdir()):
            if not step_id_dir.is_dir():
                continue
            # If this step_id_dir already has a v<N>/ child, skip entirely.
            if _has_versioned_child(step_id_dir):
                continue
            # Collect non-versioned children to wrap into v1/.
            for child in sorted(step_id_dir.iterdir()):
                if child.is_dir() and not (child.name.startswith("v") and child.name[1:].isdigit()):
                    to_migrate.append((step_id_dir, child.name))
    return to_migrate


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate Sprint 2 step paths to versioned v1/ directories."
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Preview changes without modifying files (default)"
    )
    parser.add_argument("--apply", action="store_true", help="Commit changes to disk")
    parser.add_argument(
        "--projects-root",
        default=PROJECTS_ROOT_DEFAULT,
        help=f"Root of astrid-projects (default: {PROJECTS_ROOT_DEFAULT})",
    )
    args = parser.parse_args()

    if args.apply:
        args.dry_run = False

    projects_root = Path(os.path.expanduser(args.projects_root))

    if not projects_root.exists():
        print(f"Projects root {projects_root} does not exist. Nothing to migrate.")
        return 0

    items = _find_step_dirs_to_migrate(projects_root)
    if not items:
        print("No unversioned step directories found. Workspace is clean.")
        return 0

    migrated_count = 0
    skipped_count = 0

    for step_id_dir, dir_name in items:
        old_path = step_id_dir / dir_name
        v1_dir = step_id_dir / "v1"
        new_path = v1_dir / dir_name

        rel = old_path.relative_to(projects_root) if old_path.is_relative_to(projects_root) else old_path
        print(f"  rename: {rel} → .../v1/{dir_name}")

        if args.apply:
            try:
                v1_dir.mkdir(parents=True, exist_ok=True)
                old_path.rename(new_path)
            except OSError as exc:
                print(f"  ERROR renaming {old_path}: {exc}", file=sys.stderr)
                skipped_count += 1
                continue

        migrated_count += 1

    action = "DRY-RUN" if args.dry_run else "APPLIED"
    print(
        f"Step path migration {action}: {migrated_count} directories moved, "
        f"{skipped_count} skipped (errors)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())