"""Phase 6 (SD-023) Stop-hook helper for Claude Code.

`astrid hook stop` is wired into `.claude/settings.json` (see docs/HOOKS.md)
and re-prints the current `astrid next` output (preamble + current step) so
context-decay does not erode the task-mode rules over a long run. When no
active run can be discovered the command exits 0 silently — Claude Code's
normal "free-form" sessions are unaffected.

Discovery runs in two tiers:

1. cwd-ancestor walk: climb from cwd up through its parents; if any ancestor
   is a direct child of the projects root and contains active_run.json,
   treat its name as the project slug.
2. projects-root scan: if no ancestor matched, iterate the projects root and
   pick every subdirectory whose name passes validate_project_slug and that
   contains an active_run.json.

Slugs are validated in BOTH tiers so a non-conforming cwd directory name
silently no-ops instead of leaking a confusing stderr message from cmd_next
(FLAG-P6-002).
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from typing import Iterable, Optional, Sequence

from astrid.core.project.paths import (
    ProjectPathError,
    resolve_projects_root,
    validate_project_slug,
)
from astrid.core.task.lifecycle import cmd_next


def _walk_cwd_ancestors(cwd_path: Path, root: Path) -> Optional[str]:
    for ancestor in (cwd_path, *cwd_path.parents):
        if not (ancestor / "active_run.json").is_file():
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


def _scan_projects_root(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    slugs: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            slug = validate_project_slug(child.name)
        except ProjectPathError:
            continue
        if (child / "active_run.json").is_file():
            slugs.append(slug)
    return slugs


def cmd_hook_stop(
    argv: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    projects_root: Optional[Path] = None,
) -> int:
    # argv is accepted and ignored; the Stop hook is invoked without flags.
    del argv

    cwd_path = Path(cwd).resolve() if cwd is not None else Path.cwd().resolve()
    root = resolve_projects_root(projects_root)

    slugs: Iterable[str]
    ancestor_slug = _walk_cwd_ancestors(cwd_path, root)
    if ancestor_slug is not None:
        slugs = [ancestor_slug]
    else:
        slugs = _scan_projects_root(root)

    slugs = sorted(set(slugs))
    if not slugs:
        return 0

    rc_max = 0
    outputs: list[str] = []
    for slug in slugs:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_next(["--project", slug], projects_root=root)
        outputs.append(buf.getvalue())
        if rc != 0 and rc > rc_max:
            rc_max = rc

    print("\n".join(outputs), end="")
    return rc_max
