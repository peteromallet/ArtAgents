"""ProjectTimeline persistence and placement editing APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import paths
from .jsonio import read_json, write_json_atomic
from .project import require_project
from .schema import build_placement, utc_now_iso, validate_placement, validate_project_timeline


def load_timeline(project_slug: str, *, root: str | Path | None = None) -> dict[str, Any]:
    return validate_project_timeline(read_json(paths.project_timeline_path(project_slug, root=root)))


def save_timeline(project_slug: str, timeline: dict[str, Any], *, root: str | Path | None = None) -> dict[str, Any]:
    normalized = validate_project_timeline(timeline)
    write_json_atomic(paths.project_timeline_path(project_slug, root=root), normalized)
    return normalized


def add_placement(
    project_slug: str,
    placement_id: str,
    *,
    track: str,
    at: int | float,
    source: dict[str, Any],
    from_: int | float | None = None,
    to: int | float | None = None,
    entrance: Any = None,
    exit: Any = None,
    transition: Any = None,
    effects: list[Any] | None = None,
    params: dict[str, Any] | None = None,
    root: str | Path | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    placement = build_placement(
        placement_id,
        track=track,
        at=at,
        source=source,
        from_=from_,
        to=to,
        entrance=entrance,
        exit=exit,
        transition=transition,
        effects=effects,
        params=params,
    )
    return upsert_placement(project_slug, placement, root=root, replace=replace)


def upsert_placement(
    project_slug: str,
    placement: dict[str, Any],
    *,
    root: str | Path | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    require_project(project_slug, root=root)
    normalized = validate_placement(placement)
    timeline = load_timeline(project_slug, root=root)
    placements = list(timeline.get("placements", []))
    for index, existing in enumerate(placements):
        if existing.get("id") == normalized["id"]:
            if not replace:
                raise FileExistsError(f"placement already exists: {normalized['id']}")
            placements[index] = normalized
            break
    else:
        placements.append(normalized)
    timeline["placements"] = placements
    timeline["updated_at"] = utc_now_iso()
    return save_timeline(project_slug, timeline, root=root)


def remove_placement(project_slug: str, placement_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    require_project(project_slug, root=root)
    placement_id = paths.validate_placement_id(placement_id)
    timeline = load_timeline(project_slug, root=root)
    placements = [placement for placement in timeline.get("placements", []) if placement.get("id") != placement_id]
    if len(placements) == len(timeline.get("placements", [])):
        raise FileNotFoundError(f"placement not found: {placement_id}")
    timeline["placements"] = placements
    timeline["updated_at"] = utc_now_iso()
    return save_timeline(project_slug, timeline, root=root)


def edit_placement(project_slug: str, placement_id: str, updates: dict[str, Any], *, root: str | Path | None = None) -> dict[str, Any]:
    require_project(project_slug, root=root)
    placement_id = paths.validate_placement_id(placement_id)
    if not isinstance(updates, dict):
        raise TypeError("placement updates must be an object")
    timeline = load_timeline(project_slug, root=root)
    placements = list(timeline.get("placements", []))
    for index, placement in enumerate(placements):
        if placement.get("id") == placement_id:
            edited = dict(placement)
            edited.update(updates)
            edited["id"] = placement_id
            placements[index] = validate_placement(edited)
            timeline["placements"] = placements
            timeline["updated_at"] = utc_now_iso()
            return save_timeline(project_slug, timeline, root=root)
    raise FileNotFoundError(f"placement not found: {placement_id}")
