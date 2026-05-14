"""Path and id helpers for Astrid projects."""

from __future__ import annotations

import os
import re
from pathlib import Path

PROJECTS_ROOT_ENV = "ASTRID_PROJECTS_ROOT"
DEFAULT_PROJECTS_ROOT = Path("~/Documents/reigh-workspace/astrid-projects")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class ProjectPathError(ValueError):
    """Raised when a project path component is invalid."""


def resolve_projects_root(root: str | Path | None = None) -> Path:
    raw = root if root is not None else os.environ.get(PROJECTS_ROOT_ENV)
    path = Path(raw) if raw else DEFAULT_PROJECTS_ROOT
    return path.expanduser().resolve()


def validate_project_slug(slug: object) -> str:
    if not isinstance(slug, str) or _SLUG_RE.fullmatch(slug) is None:
        raise ProjectPathError(
            "project slug must start with a lowercase letter or digit and contain only lowercase letters, digits, '-' or '_'"
        )
    return slug


def validate_source_id(source_id: object) -> str:
    if not isinstance(source_id, str) or _ID_RE.fullmatch(source_id) is None:
        raise ProjectPathError(
            "source id must start with a letter or digit and contain only letters, digits, '.', ':', '_' or '-'"
        )
    return source_id


def validate_placement_id(placement_id: object) -> str:
    if not isinstance(placement_id, str) or _ID_RE.fullmatch(placement_id) is None:
        raise ProjectPathError(
            "placement id must start with a letter or digit and contain only letters, digits, '.', ':', '_' or '-'"
        )
    return placement_id


def validate_run_id(run_id: object) -> str:
    if not isinstance(run_id, str) or _ID_RE.fullmatch(run_id) is None:
        raise ProjectPathError(
            "run id must start with a letter or digit and contain only letters, digits, '.', ':', '_' or '-'"
        )
    return run_id


def project_dir(slug: str, *, root: str | Path | None = None) -> Path:
    return resolve_projects_root(root) / validate_project_slug(slug)


def project_json_path(slug: str, *, root: str | Path | None = None) -> Path:
    return project_dir(slug, root=root) / "project.json"


def project_timeline_path(slug: str, *, root: str | Path | None = None) -> Path:
    return project_dir(slug, root=root) / "timeline.json"


def sources_dir(slug: str, *, root: str | Path | None = None) -> Path:
    return project_dir(slug, root=root) / "sources"


def source_dir(slug: str, source_id: str, *, root: str | Path | None = None) -> Path:
    return sources_dir(slug, root=root) / validate_source_id(source_id)


def source_json_path(slug: str, source_id: str, *, root: str | Path | None = None) -> Path:
    return source_dir(slug, source_id, root=root) / "source.json"


def source_analysis_dir(slug: str, source_id: str, *, root: str | Path | None = None) -> Path:
    return source_dir(slug, source_id, root=root) / "analysis"


def runs_dir(slug: str, *, root: str | Path | None = None) -> Path:
    return project_dir(slug, root=root) / "runs"


def run_dir(slug: str, run_id: str, *, root: str | Path | None = None) -> Path:
    return runs_dir(slug, root=root) / validate_run_id(run_id)


def run_json_path(slug: str, run_id: str, *, root: str | Path | None = None) -> Path:
    return run_dir(slug, run_id, root=root) / "run.json"


def run_timeline_path(slug: str, run_id: str, *, root: str | Path | None = None) -> Path:
    return run_dir(slug, run_id, root=root) / "timeline.json"


def run_assets_path(slug: str, run_id: str, *, root: str | Path | None = None) -> Path:
    return run_dir(slug, run_id, root=root) / "assets.json"


def run_metadata_path(slug: str, run_id: str, *, root: str | Path | None = None) -> Path:
    return run_dir(slug, run_id, root=root) / "metadata.json"
