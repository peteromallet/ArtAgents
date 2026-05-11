"""Per-project active-run pointer (Sprint 1 replacement for active_run.json).

Lease-first write ordering contract:

    Producers (``cmd_start``) MUST write ``runs/<id>/lease.json`` first, then
    ``<project>/current_run.json``. Readers (the WriterContext auto-rebind
    path in particular) read ``current_run.json`` first and rely on the lease
    being present — without lease-first ordering a reader could observe a
    fresh run pointer while the lease is still missing and incorrectly treat
    the run as orphaned.

Schema: ``{"run_id": "<run-id>"}``. Lease metadata (epoch, writer, plan_hash)
lives in the run's ``lease.json`` — keeping it out of this pointer avoids a
two-writer race on the same file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from astrid.core.project.jsonio import read_json, write_json_atomic
from astrid.core.project.paths import project_dir, validate_run_id


class CurrentRunError(ValueError):
    """Raised when current_run.json is malformed."""


def current_run_path(slug: str, *, root: str | Path | None = None) -> Path:
    return project_dir(slug, root=root) / "current_run.json"


def read_current_run(slug: str, *, root: str | Path | None = None) -> str | None:
    """Return the bound run id, or ``None`` when the project is detached."""

    path = current_run_path(slug, root=root)
    try:
        payload = read_json(path)
    except FileNotFoundError:
        return None
    return _validate_payload(payload, path)


def write_current_run(
    slug: str,
    run_id: str,
    *,
    root: str | Path | None = None,
) -> str:
    """Atomically point the project at ``run_id``.

    Callers MUST already have written ``runs/<run_id>/lease.json`` (see
    module docstring for the lease-first ordering contract).
    """

    validated = validate_run_id(run_id)
    write_json_atomic(current_run_path(slug, root=root), {"run_id": validated})
    return validated


def clear_current_run(slug: str, *, root: str | Path | None = None) -> None:
    current_run_path(slug, root=root).unlink(missing_ok=True)


def _validate_payload(payload: Any, path: Path) -> str:
    if not isinstance(payload, dict):
        raise CurrentRunError(f"{path} must be a JSON object")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise CurrentRunError(f"{path} run_id must be a non-empty string")
    return validate_run_id(run_id)
