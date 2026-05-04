"""Core Project and ProjectTimeline support."""

from .paths import (
    DEFAULT_PROJECTS_ROOT,
    PROJECTS_ROOT_ENV,
    project_dir,
    resolve_projects_root,
    run_dir,
    source_dir,
    validate_placement_id,
    validate_project_slug,
    validate_run_id,
    validate_source_id,
)
from .project import create_project, load_project, require_project, show_project
from .source import add_source, load_source, require_source
from .timeline import add_placement, edit_placement, load_timeline, remove_placement, save_timeline, upsert_placement

__all__ = [
    "DEFAULT_PROJECTS_ROOT",
    "PROJECTS_ROOT_ENV",
    "add_placement",
    "add_source",
    "create_project",
    "edit_placement",
    "load_project",
    "load_source",
    "load_timeline",
    "project_dir",
    "remove_placement",
    "require_project",
    "require_source",
    "resolve_projects_root",
    "run_dir",
    "save_timeline",
    "show_project",
    "source_dir",
    "upsert_placement",
    "validate_placement_id",
    "validate_project_slug",
    "validate_run_id",
    "validate_source_id",
]
