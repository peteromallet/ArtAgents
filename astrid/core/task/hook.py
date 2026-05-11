"""Stop-hook helper for Claude Code (Sprint 1 / DEC-016).

`astrid hook stop` is wired into `.claude/settings.json` (see docs/HOOKS.md)
and re-prints the current `astrid next` output (preamble + current step) so
context-decay does not erode the task-mode rules over a long run. When no
active run can be discovered the command exits 0 silently — Claude Code's
normal "free-form" sessions are unaffected.

Discovery order (DEC-016):

1. Session-bound resolution: read ``ASTRID_SESSION_ID``; if it points at a
   valid session with a bound ``project``, use that slug.
2. cwd-ancestor walk: climb from cwd up through its parents; if any
   ancestor is a direct child of the projects root and contains
   ``current_run.json``, treat its name as the project slug.

The Sprint 0 projects-root scan tier is REMOVED — multi-tab safety now
lives in the session/lease layer, and scanning the whole projects root for
the legacy ``active_run.json`` is no longer the discovery mechanism.

Slugs are validated so a non-conforming cwd directory name silently no-ops
instead of leaking a confusing stderr message from cmd_next.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from typing import Optional, Sequence

from astrid.core.project.paths import (
    ProjectPathError,
    resolve_projects_root,
    validate_project_slug,
)
from astrid.core.session.binding import SessionBindingError, resolve_current_session
from astrid.core.task.lifecycle import cmd_next


def _resolve_session_slug() -> Optional[str]:
    try:
        session = resolve_current_session()
    except SessionBindingError:
        return None
    if session is None:
        return None
    try:
        return validate_project_slug(session.project)
    except ProjectPathError:
        return None


def _walk_cwd_ancestors(cwd_path: Path, root: Path) -> Optional[str]:
    for ancestor in (cwd_path, *cwd_path.parents):
        if not (ancestor / "current_run.json").is_file():
            continue
        try:
            parent_resolved = ancestor.parent.resolve()
        except OSError:
            continue
        if parent_resolved != root:
            continue
        try:
            return validate_project_slug(ancestor.name)
        except ProjectPathError:
            return None
    return None


def cmd_hook_stop(
    argv: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    projects_root: Optional[Path] = None,
) -> int:
    del argv

    cwd_path = Path(cwd).resolve() if cwd is not None else Path.cwd().resolve()
    root = resolve_projects_root(projects_root)

    slug = _resolve_session_slug()
    if slug is None:
        slug = _walk_cwd_ancestors(cwd_path, root)

    if slug is None:
        return 0

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cmd_next(["--project", slug], projects_root=root)
    print(buf.getvalue(), end="")
    return rc
