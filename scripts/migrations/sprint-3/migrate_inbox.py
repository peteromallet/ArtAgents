#!/usr/bin/env python3
"""Migrate legacy inbox entries to schema_version:2 with plan_step_path.

Usage:
  scripts/migrations/sprint-3/migrate_inbox.py --dry-run   # default: preview
  scripts/migrations/sprint-3/migrate_inbox.py --apply      # commit changes

Walks ``runs/*/inbox/*.json`` rewriting legacy step_id-only entries to
``(plan_step_path, step_version:1, schema_version:2)``.

Resolution: for each legacy entry, walk the effective plan tree (plan.json +
replayed plan_mutated events) to find steps whose ``.id`` matches the legacy
``step_id``:

* 0 matches → ``.rejected/`` with reason ``step_id_not_found``.
* 1 match (any depth) → rewrite the entry in-place.
* >1 matches (sibling OR cross-frame ambiguity) → ``.rejected/`` with reason
  ``step_id_ambiguous_at_<n>_paths`` enumerating the candidate paths.

Idempotent: entries already carrying ``schema_version: 2`` are no-ops.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure the repo root is on sys.path so ``astrid`` is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

PROJECTS_ROOT_DEFAULT = os.path.expanduser("~/Documents/reigh-workspace/astrid-projects")

REJECTED_DIR_NAME = ".rejected"


def _effective_plan(run_dir: Path) -> "Any":
    """Return the effective TaskPlan for *run_dir* (plan.json + replayed mutations)."""
    from astrid.core.task.plan import load_plan
    from astrid.core.task.events import read_events
    from astrid.core.task.plan_verbs import apply_mutations

    plan_path = run_dir / "plan.json"
    events_path = run_dir / "events.jsonl"

    plan = load_plan(plan_path)
    if events_path.is_file():
        events = read_events(events_path)
        plan = apply_mutations(plan, events)
    return plan


def _resolve_step_id(
    plan: "Any",
    step_id: str,
) -> tuple[int, list[tuple[str, ...]]]:
    """Walk the effective plan tree and return ``(count, [paths])`` for *step_id*."""
    from astrid.core.task.plan import iter_steps_with_path

    matches: list[tuple[str, ...]] = []
    for path, step in iter_steps_with_path(plan):
        if step.id == step_id:
            matches.append(path)
    return len(matches), matches


def _move_to_rejected(file_path: Path, rejected_dir: Path) -> None:
    """Move *file_path* to ``rejected_dir/<sha256>``."""
    rejected_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    target = rejected_dir / digest
    os.replace(file_path, target)


def _migrate_entry(
    file_path: Path,
    rejected_dir: Path,
    plan: "Any",
) -> tuple[bool, str]:
    """Try to migrate a single inbox entry.

    Returns ``(acted, reason)`` where *acted* is ``True`` when the file was
    rewritten or moved, and *reason* describes the action.
    """
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _move_to_rejected(file_path, rejected_dir)
        return True, f"unreadable ({exc})"

    if not isinstance(payload, dict):
        _move_to_rejected(file_path, rejected_dir)
        return True, "payload is not a JSON object"

    # Idempotent: already-migrated entries are no-ops.
    if payload.get("schema_version") == 2:
        return False, "already schema_version:2"

    # --- Legacy entry: must carry ``step_id``. ---
    step_id = payload.get("step_id")
    if not isinstance(step_id, str) or not step_id:
        _move_to_rejected(file_path, rejected_dir)
        return True, "missing or empty step_id"

    count, paths = _resolve_step_id(plan, step_id)

    if count == 0:
        _move_to_rejected(file_path, rejected_dir)
        return True, f"step_id_not_found: {step_id!r}"

    if count > 1:
        # Enumerate candidate paths.
        enumerated = ", ".join("/".join(p) for p in paths)
        _move_to_rejected(file_path, rejected_dir)
        return True, f"step_id_ambiguous_at_{count}_paths: [{enumerated}]"

    # Exactly one match — rewrite.
    plan_step_path = list(paths[0])
    new_payload: dict[str, Any] = dict(payload)
    new_payload["schema_version"] = 2
    new_payload["plan_step_path"] = plan_step_path
    new_payload["step_version"] = 1
    # Preserve any existing submitted_by_kind; default to "agent" for legacy.
    if "submitted_by_kind" not in new_payload:
        new_payload["submitted_by_kind"] = "agent"

    file_path.write_text(
        json.dumps(new_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True, f"rewritten → {'/'.join(plan_step_path)}"


def _find_inbox_files(projects_root: Path) -> list[tuple[Path, Path]]:
    """Return ``[(run_dir, inbox_json_path), ...]`` for every inbox JSON file."""
    results: list[tuple[Path, Path]] = []
    if not projects_root.exists():
        return results

    # Structure: projects_root/<slug>/runs/<run-id>/inbox/*.json
    for inbox_dir in projects_root.glob("*/runs/*/inbox"):
        if not inbox_dir.is_dir():
            continue
        for child in sorted(inbox_dir.iterdir()):
            if child.name.startswith("."):
                continue
            if not child.is_file() or not child.suffix == ".json":
                continue
            run_dir = inbox_dir.parent  # runs/<run-id>
            results.append((run_dir, child))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate legacy inbox entries to schema_version:2."
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Preview changes without modifying files (default)",
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

    inbox_files = _find_inbox_files(projects_root)
    if not inbox_files:
        print("No inbox entries found. Workspace is clean.")
        return 0

    # Group by run_dir to load each plan only once.
    run_plans: dict[Path, Any] = {}
    for run_dir, _ in inbox_files:
        if run_dir not in run_plans:
            try:
                run_plans[run_dir] = _effective_plan(run_dir)
            except Exception as exc:
                print(f"  WARN: cannot load plan for {run_dir}: {exc}", file=sys.stderr)
                run_plans[run_dir] = None

    action_verb = "DRY-RUN" if args.dry_run else "APPLIED"
    migrated_count = 0
    skipped_count = 0
    rejected_count = 0

    for run_dir, file_path in inbox_files:
        plan = run_plans.get(run_dir)
        if plan is None:
            skipped_count += 1
            continue

        rejected_dir = run_dir / "inbox" / REJECTED_DIR_NAME
        rel = file_path.relative_to(projects_root) if file_path.is_relative_to(projects_root) else file_path

        if args.dry_run:
            # Preview: parse but don't write.
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                print(f"  skip:  {rel} (unreadable)")
                skipped_count += 1
                continue

            if not isinstance(payload, dict):
                print(f"  skip:  {rel} (not an object)")
                skipped_count += 1
                continue

            if payload.get("schema_version") == 2:
                print(f"  skip:  {rel} (already schema_version:2)")
                skipped_count += 1
                continue

            step_id = payload.get("step_id")
            if not isinstance(step_id, str) or not step_id:
                print(f"  reject: {rel} → .rejected/ (missing step_id)")
                rejected_count += 1
                continue

            count, paths = _resolve_step_id(plan, step_id)

            if count == 0:
                print(f"  reject: {rel} → .rejected/ (step_id_not_found: {step_id!r})")
                rejected_count += 1
            elif count > 1:
                enumerated = ", ".join("/".join(p) for p in paths)
                print(f"  reject: {rel} → .rejected/ (step_id_ambiguous_at_{count}_paths: [{enumerated}])")
                rejected_count += 1
            else:
                print(f"  rewrite: {rel} → {'/'.join(paths[0])}")
                migrated_count += 1
        else:
            # --apply: actually rewrite or move.
            try:
                acted, reason = _migrate_entry(file_path, rejected_dir, plan)
            except Exception as exc:
                print(f"  ERROR: {rel}: {exc}", file=sys.stderr)
                skipped_count += 1
                continue

            if not acted:
                print(f"  skip:   {rel} ({reason})")
                skipped_count += 1
            elif reason.startswith("rewritten"):
                print(f"  rewrite: {rel} ({reason})")
                migrated_count += 1
            else:
                print(f"  reject: {rel} → .rejected/ ({reason})")
                rejected_count += 1

    summary = (
        f"Inbox migration {action_verb}: {migrated_count} rewritten, "
        f"{rejected_count} rejected, {skipped_count} skipped"
    )
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())