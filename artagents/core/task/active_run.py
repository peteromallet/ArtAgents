"""Active task-run pointer helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from artagents.core.project.jsonio import read_json, write_json_atomic
from artagents.core.project.paths import project_dir, validate_run_id

_PLAN_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ActiveRunError(ValueError):
    """Raised when active_run.json is malformed."""


def read_active_run(slug: str, *, root: str | Path | None = None) -> dict[str, str] | None:
    path = _active_run_path(slug, root=root)
    try:
        payload = read_json(path)
    except FileNotFoundError:
        return None
    return _validate_active_run(payload)


def write_active_run(
    slug: str,
    *,
    run_id: str,
    plan_hash: str,
    root: str | Path | None = None,
) -> dict[str, str]:
    payload = _validate_active_run({"run_id": run_id, "plan_hash": plan_hash})
    write_json_atomic(_active_run_path(slug, root=root), payload)
    return payload


def clear_active_run(slug: str, *, root: str | Path | None = None) -> None:
    _active_run_path(slug, root=root).unlink(missing_ok=True)


def _active_run_path(slug: str, *, root: str | Path | None = None) -> Path:
    return project_dir(slug, root=root) / "active_run.json"


def _validate_active_run(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ActiveRunError("active_run.json must be an object")
    run_id = payload.get("run_id")
    plan_hash = payload.get("plan_hash")
    if not isinstance(run_id, str):
        raise ActiveRunError("active_run.json run_id must be a string")
    if not isinstance(plan_hash, str) or _PLAN_HASH_RE.fullmatch(plan_hash) is None:
        raise ActiveRunError("active_run.json plan_hash must be sha256:<64 lowercase hex>")
    return {"run_id": validate_run_id(run_id), "plan_hash": plan_hash}
