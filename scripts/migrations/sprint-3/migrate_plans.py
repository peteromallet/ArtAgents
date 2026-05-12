#!/usr/bin/env python3
"""Migrate Sprint 2 plan.json files to the Sprint 3 collapsed schema.

Usage:
  scripts/migrations/sprint-3/migrate_plans.py --dry-run   # default: preview
  scripts/migrations/sprint-3/migrate_plans.py --apply      # commit changes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure the repo root is on sys.path so `astrid` is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

PROJECTS_ROOT_DEFAULT = os.path.expanduser("~/Documents/reigh-workspace/astrid-projects")


def _read_legacy_plan_payload(path: str | Path) -> Any:
    """Load + JSON-parse a plan.json WITHOUT calling _validate_plan.

    Public load_plan() rejects version != 2; this private reader bypasses
    the gate so we can inspect and rewrite v1 plans.
    """
    from astrid.core.task.plan import _read_legacy_plan_payload as _impl
    return _impl(path)


def _migrate_step(step: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a single v1 step dict to the collapsed schema shape."""
    kind = step.get("kind", "code")  # v1 defaults to code when kind absent
    new: dict[str, Any] = {"id": step["id"], "adapter": "local", "version": 1}

    # Fields that survive any kind transition.
    for field in ("repeat", "produces", "check"):
        if field in step:
            new[field] = step[field]

    if kind in ("code", None):
        new["adapter"] = "local"
        new["assignee"] = "system"
        new["command"] = step.get("command")
        new["version"] = 1
        return new

    if kind == "attested":
        new["adapter"] = "manual"
        new["command"] = step.get("command", "")
        new["assignee"] = _broadened_assignee(step)
        new["requires_ack"] = True
        new["version"] = 1
        # Preserve instructions verbatim per SC18.
        instructions = step.get("instructions")
        if instructions:
            new["instructions"] = instructions
        # Preserve ack rule if present.
        ack = step.get("ack")
        if isinstance(ack, dict) and ack.get("kind") in ("agent", "actor"):
            new["ack"] = {"kind": ack["kind"]}
        return new

    if kind == "nested":
        child_plan = step.get("plan")
        if isinstance(child_plan, dict) and isinstance(child_plan.get("steps"), list):
            children = [_migrate_step(s) for s in child_plan["steps"]]
            new["children"] = children
            # Aggregate produces from children (best-effort).
            produces: dict[str, Any] = {}
            for child in children:
                if isinstance(child.get("produces"), dict):
                    produces.update(child["produces"])
            if produces:
                new["produces"] = produces
        # No command or other fields — it's a group step.
        new["adapter"] = "local"  # group steps keep 'local' default
        new["assignee"] = "system"
        new.pop("command", None)
        new["version"] = 1
        return new

    # Unknown kind — fall back to local.
    new["adapter"] = "local"
    new["assignee"] = "system"
    new["command"] = step.get("command")
    new["version"] = 1
    return new


def _broadened_assignee(step: dict[str, Any]) -> str:
    """Derive assignee for an attested step per SD-A broadening rules.

    SD-A: attested steps with no concrete identity get broadened to
    'any-agent' when ack.kind == 'agent' or 'any-human' when ack.kind == 'actor'.
    """
    ack = step.get("ack")
    if isinstance(ack, dict):
        if ack.get("kind") == "agent":
            return "any-agent"
        if ack.get("kind") == "actor":
            return "any-human"
    return "any-human"  # default fallback


def migrate_plan(plan_path: Path) -> tuple[bool, list[str]]:
    """Migrate a single plan.json file. Returns (changed, broadening_notes)."""
    try:
        payload = _read_legacy_plan_payload(plan_path)
    except FileNotFoundError:
        return False, {}, []
    except Exception as exc:
        print(f"  WARN: could not read {plan_path}: {exc}", file=sys.stderr)
        return False, {}, []

    if not isinstance(payload, dict):
        print(f"  WARN: {plan_path} is not a JSON object", file=sys.stderr)
        return False, {}, []

    version = payload.get("version")
    if version == 2:
        return False, {}, []  # already migrated, idempotent

    steps_raw = payload.get("steps")
    if not isinstance(steps_raw, list):
        print(f"  WARN: {plan_path} steps is not a list", file=sys.stderr)
        return False, {}, []

    migrated_steps: list[dict[str, Any]] = []
    broadening_notes: list[str] = []

    for step in steps_raw:
        if not isinstance(step, dict):
            migrated_steps.append(step)
            continue
        migrated = _migrate_step(step)
        migrated_steps.append(migrated)

        # Track assignee broadening.
        if migrated.get("assignee") in ("any-agent", "any-human"):
            step_id = migrated.get("id", step.get("id", "?"))
            broadening_notes.append(
                f"    {step_id}: {step.get('assignee', '?')} → {migrated['assignee']}"
            )

    new_payload: dict[str, Any] = {
        "plan_id": payload.get("plan_id", "unknown"),
        "version": 2,
        "steps": migrated_steps,
    }
    return True, new_payload, broadening_notes


def _find_run_dirs(projects_root: Path) -> list[Path]:
    """Return all run directories under projects_root."""
    run_dirs: list[Path] = []
    if not projects_root.exists():
        return run_dirs
    # Structure: projects_root/<slug>/runs/<run-id>
    runs_glob = projects_root.glob("*/runs/*")
    for candidate in runs_glob:
        if candidate.is_dir() and (candidate / "plan.json").exists():
            run_dirs.append(candidate)
    return sorted(run_dirs)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate Sprint 2 plan.json to Sprint 3 collapsed schema."
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
    parser.add_argument(
        "--log-path",
        default=None,
        help="Path for plan.migration.log (default: <projects-root>/plan.migration.log)",
    )
    args = parser.parse_args()

    if args.apply:
        args.dry_run = False

    projects_root = Path(os.path.expanduser(args.projects_root))
    log_path = Path(args.log_path) if args.log_path else projects_root / "plan.migration.log"

    if not projects_root.exists():
        print(f"Projects root {projects_root} does not exist. Nothing to migrate.")
        return 0

    run_dirs = _find_run_dirs(projects_root)
    if not run_dirs:
        print(f"No run directories with plan.json found under {projects_root}")
        return 0

    migrated_count = 0
    skipped_count = 0
    all_broadening_notes: list[tuple[str, list[str]]] = []

    for run_dir in run_dirs:
        plan_path = run_dir / "plan.json"
        try:
            changed, new_payload, broadening_notes = migrate_plan(plan_path)
        except Exception as exc:
            print(f"  ERROR migrating {plan_path}: {exc}", file=sys.stderr)
            skipped_count += 1
            continue

        if not changed:
            skipped_count += 1
            continue

        rel = plan_path.relative_to(projects_root) if plan_path.is_relative_to(projects_root) else plan_path
        print(f"  migrate: {rel}")

        if args.apply:
            try:
                plan_path.write_text(
                    json.dumps(new_payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                print(f"  ERROR writing {plan_path}: {exc}", file=sys.stderr)
                skipped_count += 1
                continue

        if broadening_notes:
            all_broadening_notes.append((str(rel), broadening_notes))
        migrated_count += 1

    # Write migration log.
    log_lines: list[str] = []
    if all_broadening_notes:
        total_broadened = sum(len(notes) for _, notes in all_broadening_notes)
        log_lines.append(
            f"WARNING: {total_broadened} step(s) had their assignee broadened to "
            f"any-agent/any-human. Run `astrid claim <step> --for ...` post-migration "
            f"to pin a concrete identity."
        )
        log_lines.append("")
        for plan_rel, notes in all_broadening_notes:
            log_lines.append(f"Plan: {plan_rel}")
            log_lines.extend(notes)
            log_lines.append("")

    action = "DRY-RUN" if args.dry_run else "APPLIED"
    summary = (
        f"Plan migration {action}: {migrated_count} migrated, "
        f"{skipped_count} skipped (already v2 or errors)"
    )
    print(summary)
    log_lines.insert(0, summary)
    log_lines.insert(1, "")

    if all_broadening_notes or migrated_count > 0:
        try:
            log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
            print(f"Log written to {log_path}")
        except OSError as exc:
            print(f"WARN: could not write log to {log_path}: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())