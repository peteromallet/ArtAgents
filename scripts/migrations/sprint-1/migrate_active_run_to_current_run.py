#!/usr/bin/env python3
"""Sprint 1 migration: convert ``<project>/active_run.json`` into the new
``runs/<id>/lease.json`` + ``<project>/current_run.json`` pair.

STOP-LINE behavior:

* ``--apply`` (real write) aborts non-zero on malformed input. ``--dry-run``
  (the default) PREVIEWS the abort but exits 0 so operators can survey state
  without surprising failures.
* ``--force-skip-malformed`` opts in to skip + audit malformed files and
  continue migrating the rest.
* Lease-first ordering: ``lease.json`` is written FIRST (atomic) then
  ``current_run.json`` (atomic) then ``active_run.json`` is deleted. The
  run's ``events.jsonl`` bytes are NEVER touched.

Audit logs land in a per-invocation tempfile (path printed to stderr at
exit). Idempotent: a project that already has ``current_run.json`` (and no
``active_run.json``) is a clean no-op.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from astrid.core.project.jsonio import write_json_atomic
from astrid.core.project.paths import resolve_projects_root

_PLAN_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _validate_active_run(payload: Any) -> tuple[str, str] | str:
    """Return ``(run_id, plan_hash)`` on success, or an error string."""

    if not isinstance(payload, dict):
        return "active_run.json must be an object"
    run_id = payload.get("run_id")
    plan_hash = payload.get("plan_hash")
    if not isinstance(run_id, str) or not run_id:
        return "run_id must be a non-empty string"
    if not isinstance(plan_hash, str) or _PLAN_HASH_RE.fullmatch(plan_hash) is None:
        return "plan_hash must match sha256:<64 lowercase hex>"
    return (run_id, plan_hash)


def _migrate_project(
    project_dir: Path,
    *,
    apply: bool,
    force_skip_malformed: bool,
    audit: list[dict[str, Any]],
) -> int:
    """Return 0 on success/skip; non-zero on STOP-LINE under ``--apply``."""

    active_run_path = project_dir / "active_run.json"
    if not active_run_path.exists():
        audit.append({"project": project_dir.name, "action": "no-op-absent"})
        return 0

    try:
        raw = json.loads(active_run_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result = f"invalid JSON: {exc.msg}"
    else:
        result = _validate_active_run(raw)

    if isinstance(result, str):
        reason = result
        if not apply:
            _log(f"WOULD ABORT: malformed at {active_run_path}: {reason}")
            audit.append(
                {"project": project_dir.name, "action": "would-abort", "reason": reason}
            )
            return 0
        if force_skip_malformed:
            _log(f"SKIP (forced): malformed at {active_run_path}: {reason}")
            audit.append(
                {"project": project_dir.name, "action": "skip-malformed", "reason": reason}
            )
            return 0
        _log(
            f"STOP-LINE: malformed active_run.json at {active_run_path}: "
            f"{reason}. Aborting migration."
        )
        audit.append(
            {"project": project_dir.name, "action": "abort", "reason": reason}
        )
        return 2

    run_id, plan_hash = result
    run_dir = project_dir / "runs" / run_id
    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        if not apply:
            _log(
                f"WOULD ABORT: events.jsonl missing for run {run_id} at {events_path}"
            )
            audit.append(
                {
                    "project": project_dir.name,
                    "action": "would-abort",
                    "reason": "events.jsonl missing",
                    "run_id": run_id,
                }
            )
            return 0
        _log(
            f"STOP-LINE: events.jsonl missing for run {run_id} at "
            f"{events_path}. Aborting migration."
        )
        audit.append(
            {
                "project": project_dir.name,
                "action": "abort",
                "reason": "events.jsonl missing",
                "run_id": run_id,
            }
        )
        return 2

    if not apply:
        _log(f"WOULD MIGRATE: {active_run_path} -> lease.json + current_run.json (run {run_id})")
        audit.append(
            {
                "project": project_dir.name,
                "action": "would-migrate",
                "run_id": run_id,
            }
        )
        return 0

    # Lease-first ordering: any reader that observes the new
    # current_run.json must be guaranteed to find a corresponding
    # lease.json behind it.
    lease_payload = {
        "writer_epoch": 0,
        "attached_session_id": None,
        "plan_hash": plan_hash,
    }
    write_json_atomic(run_dir / "lease.json", lease_payload)
    write_json_atomic(project_dir / "current_run.json", {"run_id": run_id})
    active_run_path.unlink()
    _log(f"MIGRATED: {project_dir.name} (run {run_id})")
    audit.append(
        {
            "project": project_dir.name,
            "action": "migrated",
            "run_id": run_id,
            "plan_hash": plan_hash,
        }
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run).")
    parser.add_argument(
        "--force-skip-malformed",
        action="store_true",
        help="Skip malformed active_run.json files instead of aborting (with --apply).",
    )
    parser.add_argument(
        "--root",
        help="Override projects root (defaults to ARTAGENTS_PROJECTS_ROOT / ~/Documents/reigh-workspace/astrid-projects).",
    )
    args = parser.parse_args(argv)
    apply = bool(args.apply)
    root = resolve_projects_root(args.root)
    if not root.exists():
        _log(f"projects root not present: {root}")
        return 0

    audit: list[dict[str, Any]] = []
    rc = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "project.json").exists():
            continue
        result = _migrate_project(
            entry,
            apply=apply,
            force_skip_malformed=args.force_skip_malformed,
            audit=audit,
        )
        if result != 0:
            rc = result
            break

    # Write audit log to a tempfile so a follow-up run can review actions.
    fd, audit_path = tempfile.mkstemp(prefix="migrate_active_run_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(
            {"apply": apply, "root": str(root), "actions": audit}, handle, indent=2
        )
    _log(f"audit log: {audit_path}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
