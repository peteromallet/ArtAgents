#!/usr/bin/env python3
"""Sprint 2 migration: rewrite legacy timeline.json files into the new container shape.

Safety
------

- ``--dry-run`` (the **default**) exits 0 without touching disk.
- ``--apply`` commits changes.
- Guards against re-running on already-migrated workspaces.
- Never touches ``plan.json``, ``events.jsonl``, or ``produces/`` directories.
- Skips hype render artifacts (files with top-level ``tracks`` or ``clips`` keys).

Usage
-----

.. code-block:: console

   # Preview what would happen.
   python3 scripts/migrations/sprint-2/migrate_timelines.py --dry-run

   # Actually migrate.
   python3 scripts/migrations/sprint-2/migrate_timelines.py --apply

   # Target a specific root.
   python3 scripts/migrations/sprint-2/migrate_timelines.py --apply --root /tmp/projects
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Resolve Astrid root so the script can import the timeline/model packages
# even when invoked from outside the repo.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent  # scripts/migrations/sprint-2 → repo root
sys.path.insert(0, str(_REPO))

from astrid.core.project.paths import (
    resolve_projects_root,
    project_json_path,
    run_dir,
    run_json_path,
)
from astrid.core.project.jsonio import read_json, write_json_atomic
from astrid.core.project.schema import validate_project, utc_now_iso
from astrid.core.timeline.model import (
    TIMELINE_SCHEMA_VERSION,
    Assembly,
    Display,
    Manifest,
)
from astrid.core.timeline.paths import (
    timeline_dir,
    timelines_dir,
    validate_timeline_ulid,
)
from astrid.threads.ids import generate_ulid, is_ulid

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def audit(project_slug: str, action: str, *, ulid: str = "", detail: str = "") -> None:
    """Write a structured audit line to stderr."""
    parts = [f"[project={project_slug}]", f"action={action}"]
    if ulid:
        parts.append(f"ulid={ulid}")
    if detail:
        parts.append(detail)
    print(" ".join(parts), file=sys.stderr)


# ---------------------------------------------------------------------------
# Step A — migrate project-level timeline.json
# ---------------------------------------------------------------------------


def _migrate_project_timeline(
    project_slug: str,
    *,
    root: Path,
    apply: bool,
) -> str | None:
    """Migrate ``<project>/timeline.json`` → ``timelines/<ulid>/``.

    Returns the ULID of the created timeline, or ``None`` if no project-level
    file existed.
    """
    legacy_path = root / project_slug / "timeline.json"
    if not legacy_path.is_file():
        return None

    audit(project_slug, "found-project-timeline", detail=f"path={legacy_path}")

    try:
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: skipping unreadable {legacy_path}: {exc}", file=sys.stderr)
        return None

    ulid = generate_ulid()
    audit(project_slug, "mint-ulid", ulid=ulid)

    tdir = timeline_dir(project_slug, ulid, root=str(root))

    # Guard: bail if the target already exists (already migrated).
    if tdir.exists():
        print(
            f"ERROR: {tdir} already exists — workspace appears already migrated. "
            f"Use --force to override.",
            file=sys.stderr,
        )
        sys.exit(1)

    if apply:
        tdir.mkdir(parents=True, exist_ok=False)
        Assembly(schema_version=TIMELINE_SCHEMA_VERSION, assembly=legacy).write(
            tdir / "assembly.json"
        )
        Manifest(
            schema_version=TIMELINE_SCHEMA_VERSION,
            contributing_runs=[],
            final_outputs=[],
            tombstoned_at=None,
        ).write(tdir / "manifest.json")
        Display(
            schema_version=TIMELINE_SCHEMA_VERSION,
            slug="default",
            name="Default",
            is_default=True,
        ).write(tdir / "display.json")
        legacy_path.unlink()
        audit(project_slug, "wrote-assembly", ulid=ulid)
        audit(project_slug, "removed-legacy", ulid=ulid, detail=f"path={legacy_path}")

    return ulid


# ---------------------------------------------------------------------------
# Step B — migrate per-run timeline.json files
# ---------------------------------------------------------------------------


def _is_hype_artifact(data: Any) -> bool:
    """Return True if *data* looks like a hype render artifact (tracks/clips)."""
    if not isinstance(data, dict):
        return False
    return "tracks" in data or "clips" in data


def _migrate_per_run_timelines(
    project_slug: str,
    project_timeline_ulid: str,
    *,
    root: Path,
    apply: bool,
) -> list[str]:
    """Walk ``<project>/runs/*/timeline.json`` and merge them into the project timeline.

    Returns the list of run ULIDs that were appended to ``contributing_runs``.
    """
    runs_root = root / project_slug / "runs"
    if not runs_root.is_dir():
        return []

    appended: list[str] = []
    found_any = False

    for run_path in sorted(runs_root.iterdir()):
        if not run_path.is_dir():
            continue
        run_legacy = run_path / "timeline.json"
        if not run_legacy.is_file():
            continue

        found_any = True
        run_id = run_path.name
        audit(project_slug, "found-run-timeline", ulid=run_id, detail=f"path={run_legacy}")

        # Read and shape-validate.
        try:
            data = json.loads(run_legacy.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(
                f"WARNING: skipping unreadable {run_legacy}: {exc}",
                file=sys.stderr,
            )
            continue

        if _is_hype_artifact(data):
            audit(
                project_slug,
                "skip-hype-artifact",
                ulid=run_id,
                detail="has tracks/clips keys — not a legacy assembly",
            )
            continue

        audit(project_slug, "append-run", ulid=run_id)

        if apply:
            tdir = timeline_dir(project_slug, project_timeline_ulid, root=str(root))
            mp = tdir / "manifest.json"
            manifest = Manifest.from_json(mp)
            if run_id not in manifest.contributing_runs:
                updated = Manifest(
                    schema_version=TIMELINE_SCHEMA_VERSION,
                    contributing_runs=list(manifest.contributing_runs) + [run_id],
                    final_outputs=list(manifest.final_outputs),
                    tombstoned_at=manifest.tombstoned_at,
                )
                updated.write(mp)
                appended.append(run_id)

            # Set run.json.timeline_id if the run has a run.json.
            rj = run_json_path(project_slug, run_id, root=str(root))
            if rj.is_file():
                run_data = read_json(rj)
                if isinstance(run_data, dict):
                    run_data["timeline_id"] = project_timeline_ulid
                    run_data["updated_at"] = utc_now_iso()
                    from astrid.core.project.schema import validate_run_record

                    write_json_atomic(rj, validate_run_record(run_data))
                    audit(project_slug, "set-run-timeline-id", ulid=run_id)

            # Remove legacy per-run timeline.json.
            run_legacy.unlink()
            audit(project_slug, "removed-run-legacy", ulid=run_id, detail=f"path={run_legacy}")

    if not found_any:
        audit(project_slug, "no-run-timelines-found")

    return appended


# ---------------------------------------------------------------------------
# Step C — update project.json default_timeline_id
# ---------------------------------------------------------------------------


def _write_default_timeline_id(
    project_slug: str,
    ulid: str,
    *,
    root: Path,
    apply: bool,
) -> None:
    """Replace the S1 sentinel (None) with the first timeline ULID."""
    pp = project_json_path(project_slug, root=str(root))
    if not pp.is_file():
        audit(project_slug, "no-project-json-skip-default")
        return

    project = validate_project(read_json(pp))
    if apply:
        project["default_timeline_id"] = ulid
        project["updated_at"] = utc_now_iso()
        write_json_atomic(pp, validate_project(project))
        audit(project_slug, "set-default-timeline-id", ulid=ulid)
    else:
        audit(project_slug, "would-set-default-timeline-id", ulid=ulid)


# ---------------------------------------------------------------------------
# Directory guard — refuse to migrate already-migrated workspaces
# ---------------------------------------------------------------------------


def _guard_not_already_migrated(project_slug: str, *, root: Path) -> None:
    """Error out if ``timelines/`` already has one or more ULID-named directories."""
    td = timelines_dir(project_slug, root=str(root))
    if td.is_dir():
        for child in td.iterdir():
            if child.is_dir() and is_ulid(child.name):
                print(
                    f"ERROR: {child} already exists — workspace appears already migrated. "
                    f"Use --force to override.",
                    file=sys.stderr,
                )
                sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sprint 2 — migrate legacy timeline.json files into the new container shape.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Override ARTAGENTS_PROJECTS_ROOT (default: ~/Documents/reigh-workspace/astrid-projects)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Commit changes to disk (default: dry-run only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        dest="dry_run",
        help="Preview changes without writing (this is the default).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Override the already-migrated guard and re-migrate.",
    )
    args = parser.parse_args(argv)

    root = resolve_projects_root(args.root)
    # --dry-run is the default; if explicitly passed, it overrides --apply.
    apply = False if args.dry_run else args.apply

    if not root.is_dir():
        print(f"INFO: projects root {root} does not exist — nothing to migrate.", file=sys.stderr)
        return 0

    projects = sorted(
        p for p in root.iterdir()
        if p.is_dir() and (p / "project.json").is_file()
    )

    if not projects:
        print(f"INFO: no projects found under {root} — nothing to migrate.", file=sys.stderr)
        return 0

    print(f"Projects root: {root}", file=sys.stderr)
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}", file=sys.stderr)
    print(f"Projects found: {len(projects)}", file=sys.stderr)
    print("---", file=sys.stderr)

    for proj_dir in projects:
        project_slug = proj_dir.name
        audit(project_slug, "processing")

        # Guard: error if already migrated.
        if not args.force:
            _guard_not_already_migrated(project_slug, root=root)

        # (A) Migrate project-level timeline.json → new container.
        first_ulid = _migrate_project_timeline(project_slug, root=root, apply=apply)

        # If no project-level file existed, we might still have per-run files.
        if first_ulid is None:
            # Check if there are any per-run legacy files that need a home.
            runs_root = root / project_slug / "runs"
            has_per_run_legacy = False
            if runs_root.is_dir():
                for rp in runs_root.iterdir():
                    if rp.is_dir() and (rp / "timeline.json").is_file():
                        has_per_run_legacy = True
                        break

            if has_per_run_legacy:
                # Create a fresh timeline to host these runs.
                audit(project_slug, "no-project-timeline-creating-fresh")
                first_ulid = generate_ulid()
                audit(project_slug, "mint-ulid", ulid=first_ulid)
                if apply:
                    tdir = timeline_dir(project_slug, first_ulid, root=str(root))
                    tdir.mkdir(parents=True, exist_ok=False)
                    Assembly(
                        schema_version=TIMELINE_SCHEMA_VERSION, assembly={}
                    ).write(tdir / "assembly.json")
                    Manifest(
                        schema_version=TIMELINE_SCHEMA_VERSION,
                        contributing_runs=[],
                        final_outputs=[],
                        tombstoned_at=None,
                    ).write(tdir / "manifest.json")
                    Display(
                        schema_version=TIMELINE_SCHEMA_VERSION,
                        slug="default",
                        name="Default",
                        is_default=True,
                    ).write(tdir / "display.json")
                    audit(project_slug, "wrote-fresh-assembly", ulid=first_ulid)

        # (B) Migrate per-run timeline.json files.
        if first_ulid is not None:
            _migrate_per_run_timelines(
                project_slug,
                first_ulid,
                root=root,
                apply=apply,
            )

            # (C) Write project.json default_timeline_id.
            _write_default_timeline_id(
                project_slug,
                first_ulid,
                root=root,
                apply=apply,
            )
        else:
            audit(project_slug, "no-legacy-files-skip")

        audit(project_slug, "done")

    print("---", file=sys.stderr)
    print(f"Migration {'applied' if apply else 'would be applied'} successfully.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())