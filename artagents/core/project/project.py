"""Project persistence APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import paths
from .jsonio import read_json, write_json_atomic
from .schema import build_project, build_project_timeline, utc_now_iso, validate_project, validate_project_timeline


class ProjectError(RuntimeError):
    """Raised when project persistence operations fail."""


def create_project(slug: str, *, name: str | None = None, root: str | Path | None = None, exist_ok: bool = False) -> dict[str, Any]:
    project_root = paths.project_dir(slug, root=root)
    project_path = project_root / "project.json"
    timeline_path = project_root / "timeline.json"
    if project_path.exists() and not exist_ok:
        raise ProjectError(f"project already exists: {slug}")
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "sources").mkdir(exist_ok=True)
    (project_root / "runs").mkdir(exist_ok=True)
    payload = build_project(slug, name=name)
    if exist_ok and project_path.exists():
        payload = validate_project(read_json(project_path))
    else:
        write_json_atomic(project_path, payload)
    if not timeline_path.exists():
        write_json_atomic(timeline_path, build_project_timeline(slug, created_at=payload.get("created_at")))
    return payload


def load_project(slug: str, *, root: str | Path | None = None) -> dict[str, Any]:
    return validate_project(read_json(paths.project_json_path(slug, root=root)))


def require_project(slug: str, *, root: str | Path | None = None) -> dict[str, Any]:
    project_path = paths.project_json_path(slug, root=root)
    if not project_path.exists():
        raise ProjectError(f"project not found: {slug}. Next command: python3 -m artagents projects create {slug}")
    return validate_project(read_json(project_path))


def load_project_timeline(slug: str, *, root: str | Path | None = None) -> dict[str, Any]:
    return validate_project_timeline(read_json(paths.project_timeline_path(slug, root=root)))


def save_project_timeline(slug: str, timeline: dict[str, Any], *, root: str | Path | None = None) -> dict[str, Any]:
    normalized = validate_project_timeline(timeline)
    write_json_atomic(paths.project_timeline_path(slug, root=root), normalized)
    _touch_project(slug, root=root)
    return normalized


def show_project(slug: str, *, root: str | Path | None = None) -> dict[str, Any]:
    project = require_project(slug, root=root)
    timeline = load_project_timeline(slug, root=root)
    source_root = paths.sources_dir(slug, root=root)
    run_root = paths.runs_dir(slug, root=root)
    sources = sorted(path.name for path in source_root.iterdir() if (path / "source.json").exists()) if source_root.exists() else []
    runs = sorted(path.name for path in run_root.iterdir() if (path / "run.json").exists()) if run_root.exists() else []
    return {
        "project": project,
        "root": str(paths.project_dir(slug, root=root)),
        "runs": runs,
        "sources": sources,
        "timeline": {
            "placements": len(timeline.get("placements", [])),
            "tracks": len(timeline.get("tracks", [])),
        },
    }


def _touch_project(slug: str, *, root: str | Path | None = None) -> None:
    payload = load_project(slug, root=root)
    payload["updated_at"] = utc_now_iso()
    write_json_atomic(paths.project_json_path(slug, root=root), validate_project(payload))
