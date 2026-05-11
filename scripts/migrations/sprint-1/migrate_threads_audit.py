#!/usr/bin/env python3
"""Sprint 1 audit (no-op): astrid/threads/ STAYS as an internal library.

Per DEC-001 the threads package is retained — only the user-facing
``astrid thread`` CLI verb is retired in T8 / T12. This script exists so
the operator runbook has a single ``scripts/migrations/sprint-1/`` invocation
sweep; it logs the discovery of threads-using callers under each project's
``runs/`` tree (variant sidecars, ThreadIndexStore tag files) so a future
sprint can confirm what is still in use before deleting.

``--apply`` and ``--dry-run`` are accepted for symmetry with the other
migration scripts. Neither actually mutates anything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from astrid.core.project.paths import resolve_projects_root


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="(no-op; symmetry only)")
    parser.add_argument("--root")
    args = parser.parse_args(argv)
    root = resolve_projects_root(args.root)

    audit: list[dict[str, Any]] = []
    if not root.exists():
        _log(f"projects root not present: {root}")
    else:
        for project_dir in sorted(root.iterdir()):
            if not project_dir.is_dir() or not (project_dir / "project.json").exists():
                continue
            runs = project_dir / "runs"
            if not runs.exists():
                continue
            for run in sorted(runs.iterdir()):
                if not run.is_dir():
                    continue
                # ThreadIndexStore tags / variant sidecars live alongside
                # the run; we just count their presence per DEC-001 audit.
                sidecars = [p.name for p in run.glob("*.thread.json")]
                if sidecars:
                    _log(
                        f"audit: {project_dir.name}/{run.name} carries {len(sidecars)} thread sidecar(s)"
                    )
                    audit.append(
                        {
                            "project": project_dir.name,
                            "run_id": run.name,
                            "thread_sidecars": sidecars,
                        }
                    )

    fd, audit_path = tempfile.mkstemp(prefix="migrate_threads_audit_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"apply": bool(args.apply), "root": str(root), "actions": audit}, handle, indent=2)
    _log(f"audit log: {audit_path}")
    _log("astrid/threads/ STAYS (DEC-001) — this is an audit only, no mutation performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
