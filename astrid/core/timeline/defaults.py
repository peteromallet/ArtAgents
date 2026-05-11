"""Per-project default-timeline pointer reader/writer."""

from __future__ import annotations

from pathlib import Path

from astrid.core.project.jsonio import read_json, write_json_atomic
from astrid.core.project.paths import project_json_path
from astrid.core.project.schema import validate_project

from .paths import validate_timeline_ulid


def read_project_default(
    project_slug: str, *, root: str | Path | None = None
) -> str | None:
    """Return the ``default_timeline_id`` ULID from ``project.json``, or ``None``.

    Returns ``None`` if ``project.json`` is missing — callers should treat
    that as "no default" rather than an error so callers (e.g. ``astrid start``
    on a freshly-set-up project) don't have to special-case bootstrap state.
    """
    pp = project_json_path(project_slug, root=root)
    if not pp.exists():
        return None
    project = validate_project(read_json(pp))
    return project.get("default_timeline_id")


def write_project_default(
    project_slug: str, ulid: str, *, root: str | Path | None = None
) -> None:
    """Set ``default_timeline_id`` to *ulid* in ``project.json``."""
    pp = project_json_path(project_slug, root=root)
    payload = validate_project(read_json(pp))
    validated = validate_timeline_ulid(ulid)
    payload["default_timeline_id"] = validated
    write_json_atomic(pp, validate_project(payload))