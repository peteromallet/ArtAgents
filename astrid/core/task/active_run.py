"""DEPRECATED compatibility shim (Sprint 1 / T9).

The old ``<project>/active_run.json`` pointer was replaced by the new
``<project>/current_run.json`` pointer + ``runs/<id>/lease.json`` pair to
end the multi-tab race that motivated the Sprint 1 reshape. This module
exists ONLY as a thin shim so callers that have not yet migrated keep
working; on-disk state is the new pair (no ``active_run.json`` is ever
written by these helpers).

Callers should migrate to:

* :func:`astrid.core.project.current_run.read_current_run` /
  :func:`write_current_run` / :func:`clear_current_run`
* :func:`astrid.core.session.lease.read_lease` /
  :func:`write_lease_init` / :func:`release_writer_lease`

The brief asks for full deletion of this module; the shim keeps existing
non-lifecycle callers functional while T10's test fixtures land. The
public symbols are NO LONGER re-exported from ``astrid.core.task``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from astrid.core.project.paths import project_dir


def _lazy_imports():
    # Deferred to break the astrid.core.task -> active_run -> lease ->
    # events -> astrid.core.task import cycle during package init.
    from astrid.core.project.current_run import (
        clear_current_run,
        read_current_run,
        write_current_run,
    )
    from astrid.core.session.lease import (
        read_lease,
        release_writer_lease,
        write_lease_init,
    )

    return (
        clear_current_run,
        read_current_run,
        write_current_run,
        read_lease,
        release_writer_lease,
        write_lease_init,
    )


class ActiveRunError(ValueError):
    """Retained for backward compatibility with pre-Sprint-1 callers."""


def read_active_run(slug: str, *, root: str | Path | None = None) -> dict[str, str] | None:
    """Return ``{run_id, plan_hash}`` by reading current_run.json + lease.json."""

    _, read_current_run, _, read_lease, _, _ = _lazy_imports()
    run_id = read_current_run(slug, root=root)
    if run_id is None:
        return None
    run_dir = project_dir(slug, root=root) / "runs" / run_id
    lease = read_lease(run_dir)
    plan_hash = lease.get("plan_hash") or ""
    return {"run_id": run_id, "plan_hash": plan_hash}


def write_active_run(
    slug: str,
    *,
    run_id: str,
    plan_hash: str,
    root: str | Path | None = None,
) -> dict[str, str]:
    """Lease-first then current_run write. Used by legacy callers that
    cannot reach a Session — modern callers (cmd_start) should call
    :func:`write_lease_init` + :func:`write_current_run` explicitly so the
    session id ends up on the lease.

    Lease-first ordering: any reader that observes the new
    ``current_run.json`` is guaranteed to find a corresponding
    ``lease.json``.
    """

    _, _, write_current_run, _, _, write_lease_init = _lazy_imports()
    run_dir = project_dir(slug, root=root) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    # ``'legacy'`` as the lease session marker: pre-Sprint-1 callers don't
    # carry a Session; WriterContext-aware callers should call
    # write_lease_init(session_id=session.id) explicitly.
    write_lease_init(run_dir, session_id="legacy", plan_hash=plan_hash)
    write_current_run(slug, run_id, root=root)
    return {"run_id": run_id, "plan_hash": plan_hash}


def clear_active_run(slug: str, *, root: str | Path | None = None) -> None:
    """Clear both ``current_run.json`` and release the writer lease."""

    clear_current_run, read_current_run, _, _, release_writer_lease, _ = _lazy_imports()
    run_id = read_current_run(slug, root=root)
    if run_id is not None:
        run_dir = project_dir(slug, root=root) / "runs" / run_id
        try:
            release_writer_lease(run_dir)
        except FileNotFoundError:
            pass
    clear_current_run(slug, root=root)
