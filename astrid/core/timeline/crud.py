"""Timeline CRUD primitives — create, list, show, rename, finalize, tombstone, purge, set-default."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrid.core.project.jsonio import read_json, write_json_atomic
from astrid.core.project.project import load_project
from astrid.threads.ids import generate_ulid

from .integrity import compute_sha256, file_size
from .model import (
    TIMELINE_SCHEMA_VERSION,
    Assembly,
    Display,
    FinalOutput,
    Manifest,
    TimelineValidationError,
)
from .paths import (
    display_path,
    find_timeline_by_slug,
    find_timeline_slug_for_ulid,
    timeline_dir,
    timelines_dir,
    validate_timeline_slug,
)


class TimelineCrudError(RuntimeError):
    """Raised when a timeline CRUD operation cannot be completed."""


@dataclass(frozen=True)
class TimelineSummary:
    """Lightweight timeline listing row."""

    ulid: str
    slug: str
    name: str
    is_default: bool
    run_count: int
    final_output_count: int
    last_finalized: str | None  # ISO-8601 timestamp of the most recent final output


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_timeline(
    project_slug: str,
    slug: str,
    *,
    name: str | None = None,
    is_default: bool = False,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Create a new timeline container under *project_slug*.

    Returns a dict with keys ``ulid``, ``slug``, ``display``, ``assembly``, ``manifest``.
    """
    slug = validate_timeline_slug(slug)
    human_name = name or slug

    # Refuse duplicate slug within the same project.
    existing = find_timeline_by_slug(project_slug, slug, root=root)
    if existing is not None:
        raise TimelineCrudError(
            f"timeline slug '{slug}' already exists in project '{project_slug}' "
            f"(ULID {existing[0]})"
        )

    ulid = generate_ulid()
    tdir = timeline_dir(project_slug, ulid, root=root)
    tdir.mkdir(parents=True, exist_ok=False)

    assembly = Assembly(schema_version=TIMELINE_SCHEMA_VERSION, assembly={})
    manifest = Manifest(
        schema_version=TIMELINE_SCHEMA_VERSION,
        contributing_runs=[],
        final_outputs=[],
        tombstoned_at=None,
    )
    display = Display(
        schema_version=TIMELINE_SCHEMA_VERSION,
        slug=slug,
        name=human_name,
        is_default=is_default,
    )

    assembly.write(tdir / "assembly.json")
    manifest.write(tdir / "manifest.json")
    display.write(tdir / "display.json")

    if is_default:
        _set_project_default(project_slug, ulid, root=root)

    return {
        "ulid": ulid,
        "slug": slug,
        "display": display,
        "assembly": assembly,
        "manifest": manifest,
    }


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def list_timelines(
    project_slug: str,
    *,
    root: str | Path | None = None,
) -> list[TimelineSummary]:
    """Return summary rows for every timeline under *project_slug*."""
    td = timelines_dir(project_slug, root=root)
    if not td.is_dir():
        return []

    project = load_project(project_slug, root=root)
    default_ulid = project.get("default_timeline_id")

    rows: list[TimelineSummary] = []
    for child in sorted(td.iterdir()):
        if not child.is_dir():
            continue
        ulid = child.name
        dp = child / "display.json"
        mp = child / "manifest.json"
        if not dp.is_file():
            continue

        try:
            display = Display.from_json(dp)
        except (TimelineValidationError, OSError):
            continue

        run_count = 0
        final_output_count = 0
        last_finalized: str | None = None
        if mp.is_file():
            try:
                manifest = Manifest.from_json(mp)
            except (TimelineValidationError, OSError):
                manifest = None
            if manifest is not None:
                run_count = len(manifest.contributing_runs)
                final_output_count = len(manifest.final_outputs)
                if manifest.final_outputs:
                    last_finalized = max(
                        (fo.recorded_at for fo in manifest.final_outputs),
                        default=None,
                    )

        rows.append(
            TimelineSummary(
                ulid=ulid,
                slug=display.slug,
                name=display.name,
                is_default=(ulid == default_ulid),
                run_count=run_count,
                final_output_count=final_output_count,
                last_finalized=last_finalized,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------


def show_timeline(
    project_slug: str,
    slug: str,
    *,
    root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return the full timeline record (assembly + manifest + display)."""
    found = find_timeline_by_slug(project_slug, slug, root=root)
    if found is None:
        return None
    ulid, tdir = found
    assembly = Assembly.from_json(tdir / "assembly.json")
    manifest = Manifest.from_json(tdir / "manifest.json")
    display = Display.from_json(tdir / "display.json")
    return {
        "ulid": ulid,
        "display": display,
        "assembly": assembly,
        "manifest": manifest,
    }


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------


def rename_timeline(
    project_slug: str,
    old_slug: str,
    new_slug: str,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Rewrite ``display.json`` so *old_slug* becomes *new_slug*.

    Refuses if *new_slug* is already taken within the same project.
    """
    found = find_timeline_by_slug(project_slug, old_slug, root=root)
    if found is None:
        raise TimelineCrudError(f"timeline '{old_slug}' not found in project '{project_slug}'")

    ulid, tdir = found
    new_slug = validate_timeline_slug(new_slug)

    # Check collision.
    collision = find_timeline_by_slug(project_slug, new_slug, root=root)
    if collision is not None and collision[0] != ulid:
        raise TimelineCrudError(
            f"timeline slug '{new_slug}' already exists in project '{project_slug}'"
        )

    dp = tdir / "display.json"
    display = Display.from_json(dp)
    updated = Display(
        schema_version=TIMELINE_SCHEMA_VERSION,
        slug=new_slug,
        name=display.name,
        is_default=display.is_default,
    )
    updated.write(dp)
    return {"ulid": ulid, "slug": new_slug, "display": updated}


# ---------------------------------------------------------------------------
# Finalize output
# ---------------------------------------------------------------------------


def finalize_output(
    project_slug: str,
    slug: str,
    output_path: str | Path,
    *,
    kind: str = "unknown",
    from_run: str | None = None,
    recorded_by: str = "agent:unknown",
    root: str | Path | None = None,
) -> FinalOutput:
    """Capture sha256 + size of *output_path* and append to the timeline's final outputs.

    ``check_status`` is stamped ``"ok"`` at call time; ``check_at`` equals ``recorded_at``.
    """
    found = find_timeline_by_slug(project_slug, slug, root=root)
    if found is None:
        raise TimelineCrudError(f"timeline '{slug}' not found in project '{project_slug}'")

    ulid, tdir = found
    op = Path(output_path).expanduser().resolve()
    if not op.is_file():
        raise TimelineCrudError(f"output file not found: {op}")

    from astrid.core.project.schema import utc_now_iso

    now = utc_now_iso()
    sha256 = compute_sha256(op)
    size = file_size(op)

    fo = FinalOutput(
        ulid=generate_ulid(),
        path=str(op),
        kind=kind,
        size=size,
        sha256=sha256,
        check_status="ok",
        check_at=now,
        recorded_at=now,
        recorded_by=recorded_by,
        from_run=from_run or "",
    )

    mp = tdir / "manifest.json"
    manifest = Manifest.from_json(mp)
    new_outputs = list(manifest.final_outputs) + [fo]
    updated = Manifest(
        schema_version=TIMELINE_SCHEMA_VERSION,
        contributing_runs=list(manifest.contributing_runs),
        final_outputs=new_outputs,
        tombstoned_at=manifest.tombstoned_at,
    )
    updated.write(mp)
    return fo


# ---------------------------------------------------------------------------
# Tombstone
# ---------------------------------------------------------------------------


def tombstone_timeline(
    project_slug: str,
    slug: str,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Soft-delete: stamp ``tombstoned_at`` in the manifest, leave files in place."""
    found = find_timeline_by_slug(project_slug, slug, root=root)
    if found is None:
        raise TimelineCrudError(f"timeline '{slug}' not found in project '{project_slug}'")

    ulid, tdir = found
    mp = tdir / "manifest.json"
    manifest = Manifest.from_json(mp)

    if manifest.tombstoned_at is not None:
        raise TimelineCrudError(f"timeline '{slug}' is already tombstoned")

    from astrid.core.project.schema import utc_now_iso

    updated = Manifest(
        schema_version=TIMELINE_SCHEMA_VERSION,
        contributing_runs=list(manifest.contributing_runs),
        final_outputs=list(manifest.final_outputs),
        tombstoned_at=utc_now_iso(),
    )
    updated.write(mp)
    return {"ulid": ulid, "slug": slug, "tombstoned_at": updated.tombstoned_at}


# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------


def purge_timeline(
    project_slug: str,
    slug: str,
    *,
    root: str | Path | None = None,
) -> None:
    """Hard-delete the timeline directory tree.

    Refuses if the timeline is currently the project default — callers MUST
    ``set_default`` to a different timeline first.
    """
    found = find_timeline_by_slug(project_slug, slug, root=root)
    if found is None:
        raise TimelineCrudError(f"timeline '{slug}' not found in project '{project_slug}'")

    ulid, tdir = found

    # Refuse if this is the project default.
    project = load_project(project_slug, root=root)
    if project.get("default_timeline_id") == ulid:
        raise TimelineCrudError(
            f"timeline '{slug}' is the project default; "
            f"set another timeline as default first with 'astrid timelines set-default <other>'"
        )

    shutil.rmtree(tdir)


# ---------------------------------------------------------------------------
# Set default
# ---------------------------------------------------------------------------


def set_default(
    project_slug: str,
    slug: str,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Make *slug* the project default timeline.

    Rewrites ``display.json`` on the old default (clearing its ``is_default``),
    on the new one (setting ``is_default``), and updates ``project.json``
    ``default_timeline_id``.
    """
    found = find_timeline_by_slug(project_slug, slug, root=root)
    if found is None:
        raise TimelineCrudError(f"timeline '{slug}' not found in project '{project_slug}'")

    new_ulid, new_tdir = found

    # Clear old default.
    project = load_project(project_slug, root=root)
    old_ulid = project.get("default_timeline_id")
    if old_ulid is not None and old_ulid != new_ulid:
        old_dp = display_path(project_slug, old_ulid, root=root)
        if old_dp.is_file():
            try:
                old_display = Display.from_json(old_dp)
            except (TimelineValidationError, OSError):
                old_display = None
            if old_display is not None and old_display.is_default:
                cleared = Display(
                    schema_version=TIMELINE_SCHEMA_VERSION,
                    slug=old_display.slug,
                    name=old_display.name,
                    is_default=False,
                )
                cleared.write(old_dp)

    # Set new default.
    new_dp = new_tdir / "display.json"
    new_display = Display.from_json(new_dp)
    updated = Display(
        schema_version=TIMELINE_SCHEMA_VERSION,
        slug=new_display.slug,
        name=new_display.name,
        is_default=True,
    )
    updated.write(new_dp)

    # Update project.json.
    _set_project_default(project_slug, new_ulid, root=root)

    return {"ulid": new_ulid, "slug": slug, "display": updated}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _set_project_default(
    project_slug: str,
    ulid: str,
    *,
    root: str | Path | None = None,
) -> None:
    """Rewrite ``project.json`` so ``default_timeline_id`` points at *ulid*."""
    from astrid.core.project.paths import project_json_path
    from astrid.core.project.schema import validate_project

    pp = project_json_path(project_slug, root=root)
    payload = validate_project(read_json(pp))
    payload["default_timeline_id"] = ulid
    write_json_atomic(pp, validate_project(payload))