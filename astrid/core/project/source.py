"""Source persistence APIs for projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import paths
from .jsonio import read_json, write_json_atomic
from .project import require_project
from .schema import build_source, validate_source


def add_source(
    project_slug: str,
    source_id: str,
    *,
    asset: dict[str, Any],
    kind: str | None = None,
    metadata: dict[str, Any] | None = None,
    root: str | Path | None = None,
    exist_ok: bool = False,
) -> dict[str, Any]:
    require_project(project_slug, root=root)
    source_path = paths.source_json_path(project_slug, source_id, root=root)
    if source_path.exists() and not exist_ok:
        raise FileExistsError(f"source already exists: {source_id}")
    paths.source_analysis_dir(project_slug, source_id, root=root).mkdir(parents=True, exist_ok=True)
    payload = build_source(project_slug, source_id, asset=asset, kind=kind, metadata=metadata)
    write_json_atomic(source_path, payload)
    return payload


def load_source(project_slug: str, source_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    return validate_source(read_json(paths.source_json_path(project_slug, source_id, root=root)))


def require_source(project_slug: str, source_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    source_path = paths.source_json_path(project_slug, source_id, root=root)
    if not source_path.exists():
        raise FileNotFoundError(
            f"source not found: {source_id}. Next command: python3 -m astrid projects source add --project {project_slug} {source_id} --file <path>"
        )
    return validate_source(read_json(source_path))
