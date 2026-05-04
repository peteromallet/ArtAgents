"""Core Project local-cache support (project.json + sources/ + runs/).

The parallel placement schema (timeline.py, materialize.py, build_placement,
validate_project_timeline, etc.) was collapsed in T10. Live timeline state now
lives on reigh-app's ``timelines`` rows; AA reads/writes via
``artagents.core.reigh.SupabaseDataProvider``.
"""

from .paths import (
    DEFAULT_PROJECTS_ROOT,
    PROJECTS_ROOT_ENV,
    project_dir,
    resolve_projects_root,
    run_dir,
    source_dir,
    validate_project_slug,
    validate_run_id,
    validate_source_id,
)
from .project import create_project, load_project, require_project, show_project
from .source import add_source, load_source, require_source

__all__ = [
    "DEFAULT_PROJECTS_ROOT",
    "PROJECTS_ROOT_ENV",
    "add_source",
    "create_project",
    "load_project",
    "load_source",
    "project_dir",
    "require_project",
    "require_source",
    "resolve_projects_root",
    "run_dir",
    "show_project",
    "source_dir",
    "validate_project_slug",
    "validate_run_id",
    "validate_source_id",
]
