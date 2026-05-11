"""Path and id helpers for Astrid timelines."""

from __future__ import annotations

import re
from pathlib import Path

from astrid.threads.ids import is_ulid

from ..project.paths import ProjectPathError, project_dir, resolve_projects_root

_TIMELINE_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def validate_timeline_slug(slug: object) -> str:
    if not isinstance(slug, str) or _TIMELINE_SLUG_RE.fullmatch(slug) is None:
        raise ProjectPathError(
            "timeline slug must start with a lowercase letter, contain only "
            "lowercase letters, digits or '-', and be 1–32 characters long"
        )
    return slug


def validate_timeline_ulid(ulid: object) -> str:
    if not is_ulid(ulid):
        raise ProjectPathError(
            "timeline ULID must be a 26-character Crockford ULID"
        )
    return str(ulid)


def timelines_dir(project_slug: str, *, root: str | Path | None = None) -> Path:
    return project_dir(project_slug, root=root) / "timelines"


def timeline_dir(
    project_slug: str, ulid: str, *, root: str | Path | None = None
) -> Path:
    return timelines_dir(project_slug, root=root) / validate_timeline_ulid(ulid)


def assembly_path(
    project_slug: str, ulid: str, *, root: str | Path | None = None
) -> Path:
    return timeline_dir(project_slug, ulid, root=root) / "assembly.json"


def manifest_path(
    project_slug: str, ulid: str, *, root: str | Path | None = None
) -> Path:
    return timeline_dir(project_slug, ulid, root=root) / "manifest.json"


def display_path(
    project_slug: str, ulid: str, *, root: str | Path | None = None
) -> Path:
    return timeline_dir(project_slug, ulid, root=root) / "display.json"


def find_timeline_by_slug(
    project_slug: str, slug: str, *, root: str | Path | None = None
) -> tuple[str, Path] | None:
    """Scan timelines/*/display.json for a matching slug.

    Returns (ulid, timeline_dir) or None if not found.
    """
    import json

    target = validate_timeline_slug(slug)
    td = timelines_dir(project_slug, root=root)
    if not td.is_dir():
        return None
    for child in sorted(td.iterdir()):
        if not child.is_dir():
            continue
        dp = child / "display.json"
        if not dp.is_file():
            continue
        try:
            data = json.loads(dp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and data.get("slug") == target:
            # The directory name is the ULID.
            return (child.name, child)
    return None


def find_timeline_slug_for_ulid(
    project_slug: str, ulid: str, *, root: str | Path | None = None
) -> str | None:
    """Reverse-lookup: read display.json for the given ULID and return the slug."""
    import json

    dp = display_path(project_slug, ulid, root=root)
    if not dp.is_file():
        return None
    try:
        data = json.loads(dp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(data, dict):
        slug = data.get("slug")
        if isinstance(slug, str):
            return slug
    return None