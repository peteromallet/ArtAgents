"""Resolve the current tab's session from ``ASTRID_SESSION_ID``.

The session record is the authoritative binding for a tab; the env var
just points at it. Subprocesses inherit ``ASTRID_SESSION_ID`` (Sprint 0
env-inheritance spike confirms this); do not silently scrub it.
"""

from __future__ import annotations

import os
from pathlib import Path

from astrid.core.project.paths import project_dir
from astrid.core.session.lease import read_lease
from astrid.core.session.model import Session, SessionValidationError
from astrid.core.session.paths import session_path

ASTRID_SESSION_ID_ENV = "ASTRID_SESSION_ID"


class SessionBindingError(RuntimeError):
    """Raised when the session-binding env var points at a missing/invalid record."""


def resolve_current_session() -> Session | None:
    """Return the current tab's :class:`Session`, or ``None`` if unbound.

    Unbound = ``ASTRID_SESSION_ID`` is unset OR set to an empty string.
    The CLI gate (T8) is what converts ``None`` into a "no session bound"
    error for verbs outside the unbound allowlist.
    """

    raw = os.environ.get(ASTRID_SESSION_ID_ENV)
    if not raw:
        return None
    path = session_path(raw)
    try:
        return Session.from_json(path)
    except FileNotFoundError as exc:
        raise SessionBindingError(
            f"ASTRID_SESSION_ID={raw!r} but no session file at {path}; "
            "did you `astrid attach <project>` or detach?"
        ) from exc
    except SessionValidationError as exc:
        raise SessionBindingError(
            f"ASTRID_SESSION_ID={raw!r} points at a malformed session file: {exc}"
        ) from exc


def is_writer_for(session: Session, run_dir: str | Path) -> bool:
    """Return True iff this session currently holds the lease for ``run_dir``."""

    lease = read_lease(run_dir)
    return lease.get("attached_session_id") == session.id


def current_run_dir(session: Session, *, root: str | Path | None = None) -> Path | None:
    """Return the run directory bound to this session, or ``None`` when run_id is unset."""

    if session.run_id is None:
        return None
    return project_dir(session.project, root=root) / "runs" / session.run_id
