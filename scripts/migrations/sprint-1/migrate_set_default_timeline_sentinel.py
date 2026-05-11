#!/usr/bin/env python3
"""Sprint 1 migration: write the ``default_timeline_id: null`` sentinel into
each project's ``project.json``.

Sprint 2 wires the actual timeline container; backfilling later across an
entire project tree is painful, so we stamp the key now while we already
hold the file open. The migration:

* Loads every ``project.json`` under the projects root via the canonical
  validator (so legacy files round-trip cleanly).
* Inserts ``default_timeline_id: None`` when absent. Preserves an existing
  slug or ``None`` value unchanged.
* Re-validates the updated payload before atomic write.
* Skips files that already carry the key (idempotent).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from astrid.core.project.jsonio import read_json, write_json_atomic
from astrid.core.project.paths import resolve_projects_root
from astrid.core.project.schema import ProjectValidationError, validate_project


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _migrate(project_json: Path, *, apply: bool, audit: list[dict[str, Any]]) -> int:
    try:
        payload = read_json(project_json)
    except FileNotFoundError:
        return 0
    try:
        validated = validate_project(payload)
    except ProjectValidationError as exc:
        if not apply:
            _log(f"WOULD ABORT: invalid {project_json}: {exc}")
            audit.append({"path": str(project_json), "action": "would-abort", "reason": str(exc)})
            return 0
        _log(f"STOP-LINE: invalid {project_json}: {exc}. Aborting migration.")
        audit.append({"path": str(project_json), "action": "abort", "reason": str(exc)})
        return 2

    if "default_timeline_id" in validated:
        audit.append({"path": str(project_json), "action": "no-op-already-stamped"})
        return 0

    updated = dict(validated)
    updated["default_timeline_id"] = None
    # Re-validate to make sure the new payload still round-trips.
    validate_project(updated)
    if not apply:
        _log(f"WOULD STAMP: {project_json}")
        audit.append({"path": str(project_json), "action": "would-stamp"})
        return 0
    write_json_atomic(project_json, updated)
    _log(f"STAMPED: {project_json}")
    audit.append({"path": str(project_json), "action": "stamped"})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--root")
    args = parser.parse_args(argv)
    root = resolve_projects_root(args.root)
    if not root.exists():
        _log(f"projects root not present: {root}")
        return 0

    audit: list[dict[str, Any]] = []
    rc = 0
    for entry in sorted(root.iterdir()):
        project_json = entry / "project.json"
        if not project_json.exists():
            continue
        result = _migrate(project_json, apply=bool(args.apply), audit=audit)
        if result != 0:
            rc = result
            break

    fd, audit_path = tempfile.mkstemp(prefix="migrate_default_timeline_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"apply": bool(args.apply), "root": str(root), "actions": audit}, handle, indent=2)
    _log(f"audit log: {audit_path}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
