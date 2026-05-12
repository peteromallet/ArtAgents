"""Project persistence APIs.

After the placement-schema collapse (T10), local ``project.json`` keeps an
opaque ``project_id`` that points at the canonical reigh-app row. Local
``timeline.json`` is no longer the source of truth — timeline reads/writes go
through ``astrid.core.reigh.SupabaseDataProvider``. The local provenance
cache (``sources/`` and ``runs/`` directories) survives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import paths
from .jsonio import read_json, write_json_atomic
from .schema import build_project, utc_now_iso, validate_project

# Skeleton for the per-project plan.md — a human/agent-readable working notes
# doc at the project root.  This is DISTINCT from <project>/runs/<run-id>/plan.json
# which is the executable runtime step tree; plan.md is project-level prose for
# current focus, open threads, key decisions, and scratch notes.
_PLAN_MD_SKELETON = """# {slug} — Plan

_Live working notes for this project. Read on attach; keep updated as the plan evolves._

## Current focus



## Open threads



## Key decisions



## Notes

"""


class ProjectError(RuntimeError):
    """Raised when project persistence operations fail."""


def create_project(
    slug: str,
    *,
    name: str | None = None,
    project_id: str | None = None,
    root: str | Path | None = None,
    exist_ok: bool = False,
) -> dict[str, Any]:
    project_root = paths.project_dir(slug, root=root)
    project_path = project_root / "project.json"

    # Pre-check: reject if a directory with this slug already exists under the
    # projects root.  Projects under different ARTAGENTS_PROJECTS_ROOT values
    # are independent — each root is checked separately.
    if project_root.exists() and not exist_ok:
        raise ProjectError(f"project '{slug}' already exists at {project_root}")

    if project_path.exists() and not exist_ok:
        raise ProjectError(f"project already exists: {slug}")
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "sources").mkdir(exist_ok=True)
    (project_root / "runs").mkdir(exist_ok=True)
    payload = build_project(slug, name=name, project_id=project_id)
    if exist_ok and project_path.exists():
        payload = validate_project(read_json(project_path))
    else:
        write_json_atomic(project_path, payload)
    # plan.md: per-project human/agent working notes at the project root.
    # Distinct from runs/<run-id>/plan.json (the runtime step tree).
    # Idempotent — if it already exists, leave it alone.
    plan_path = project_root / "plan.md"
    if not plan_path.exists():
        _write_text_atomic(plan_path, _PLAN_MD_SKELETON.format(slug=slug))
    return payload


def _write_text_atomic(path: Path, content: str) -> None:
    """Atomic text write — temp file in same dir, then rename."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def load_project(slug: str, *, root: str | Path | None = None) -> dict[str, Any]:
    return validate_project(read_json(paths.project_json_path(slug, root=root)))


def require_project(slug: str, *, root: str | Path | None = None) -> dict[str, Any]:
    project_path = paths.project_json_path(slug, root=root)
    if not project_path.exists():
        raise ProjectError(f"project not found: {slug}. Next command: python3 -m astrid projects create {slug}")
    return validate_project(read_json(project_path))


def show_project(slug: str, *, root: str | Path | None = None) -> dict[str, Any]:
    """Return a cache-only view of the project tree.

    Live timeline state (clip count, theme, etc.) lives on the canonical
    reigh-app row keyed by ``project.project_id``. Callers that need it should
    use ``astrid.core.reigh.SupabaseDataProvider.load_timeline`` directly;
    this helper deliberately stays offline so ``projects show`` works without
    network access.
    """

    project = require_project(slug, root=root)
    source_root = paths.sources_dir(slug, root=root)
    run_root = paths.runs_dir(slug, root=root)
    sources = sorted(path.name for path in source_root.iterdir() if (path / "source.json").exists()) if source_root.exists() else []
    runs = sorted(path.name for path in run_root.iterdir() if (path / "run.json").exists()) if run_root.exists() else []
    return {
        "project": project,
        "project_id": project.get("project_id"),
        "root": str(paths.project_dir(slug, root=root)),
        "runs": runs,
        "sources": sources,
    }


def _touch_project(slug: str, *, root: str | Path | None = None) -> None:
    payload = load_project(slug, root=root)
    payload["updated_at"] = utc_now_iso()
    write_json_atomic(paths.project_json_path(slug, root=root), validate_project(payload))
