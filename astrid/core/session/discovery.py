"""Project discovery for the unbound-status / first-run-bootstrap UX."""

from __future__ import annotations

from pathlib import Path

from astrid.core.project.paths import resolve_projects_root


def discover_projects(*, root: str | Path | None = None) -> list[str]:
    """Return project slugs under the projects root, sorted by mtime descending.

    Most-recently-used first matches what an operator actually wants to see
    when ``astrid status`` lists candidates after a fresh tab.
    """

    projects_root = resolve_projects_root(root)
    if not projects_root.exists():
        return []
    candidates: list[tuple[float, str]] = []
    for entry in projects_root.iterdir():
        if not entry.is_dir():
            continue
        if not (entry / "project.json").exists():
            continue
        candidates.append((entry.stat().st_mtime, entry.name))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [name for _, name in candidates]
