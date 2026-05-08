"""Project file schemas and validators (project / source / run only).

The parallel placement schema (build_project_timeline / build_placement /
validate_project_timeline / validate_placement / validate_reference / REF_KINDS
/ source_ref / run_ref / TIMELINE_SCHEMA_VERSION) was removed when AA collapsed
onto reigh-app's canonical ``timelines`` rows. Timeline reads/writes now go
through ``astrid.core.reigh.SupabaseDataProvider``; the local provenance
cache (sources/, runs/, project.json) is what survives.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import validate_project_slug, validate_run_id, validate_source_id

PROJECT_SCHEMA_VERSION = 1
SOURCE_SCHEMA_VERSION = 1
RUN_SCHEMA_VERSION = 1
SOURCE_KINDS = {"audio", "image", "other", "video"}
RUN_STATUSES = {"prepared", "success", "failed", "skipped", "error"}


class ProjectValidationError(ValueError):
    """Raised when project state fails validation."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_project(
    slug: str,
    *,
    name: str | None = None,
    project_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    now = created_at or utc_now_iso()
    slug = validate_project_slug(slug)
    payload: dict[str, Any] = {
        "created_at": now,
        "name": name or slug,
        "schema_version": PROJECT_SCHEMA_VERSION,
        "slug": slug,
        "updated_at": now,
    }
    if project_id is not None:
        payload["project_id"] = _require_string(project_id, "project.project_id")
    return payload


def build_source(
    project_slug: str,
    source_id: str,
    *,
    asset: dict[str, Any],
    kind: str | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    now = created_at or utc_now_iso()
    normalized_asset = _normalize_asset(asset, path="source.asset")
    return {
        "asset": normalized_asset,
        "created_at": now,
        "kind": validate_source_kind(kind or _infer_source_kind(normalized_asset), path="source.kind"),
        "metadata": dict(metadata or {}),
        "project_slug": validate_project_slug(project_slug),
        "schema_version": SOURCE_SCHEMA_VERSION,
        "source_id": validate_source_id(source_id),
        "updated_at": now,
    }


def build_run_record(
    project_slug: str,
    run_id: str,
    *,
    tool_id: str | None = None,
    kind: str | None = None,
    status: str = "prepared",
    out: str | Path | None = None,
    argv: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    now = created_at or utc_now_iso()
    payload: dict[str, Any] = {
        "artifacts": dict(artifacts or {}),
        "created_at": now,
        "metadata": dict(metadata or {}),
        "project_slug": validate_project_slug(project_slug),
        "run_id": validate_run_id(run_id),
        "schema_version": RUN_SCHEMA_VERSION,
        "status": status,
        "updated_at": now,
    }
    if tool_id is not None:
        payload["tool_id"] = _require_string(tool_id, "run.tool_id")
    if kind is not None:
        payload["kind"] = _require_string(kind, "run.kind")
    if out is not None:
        payload["out"] = str(out)
    if argv is not None:
        payload["argv"] = [_require_string(item, "run.argv[]") for item in argv]
    return validate_run_record(payload)


def validate_project(raw: Any) -> dict[str, Any]:
    data = _require_mapping(raw, "project")
    _require_version(data, PROJECT_SCHEMA_VERSION, "project")
    slug = validate_project_slug(_require_string(data.get("slug"), "project.slug"))
    name = _require_string(data.get("name"), "project.name")
    created_at = _require_string(data.get("created_at"), "project.created_at")
    updated_at = _require_string(data.get("updated_at"), "project.updated_at")
    payload = dict(data)
    payload.update({"created_at": created_at, "name": name, "slug": slug, "updated_at": updated_at})
    if "project_id" in payload:
        if payload["project_id"] is None:
            payload.pop("project_id")
        else:
            payload["project_id"] = _require_string(payload["project_id"], "project.project_id")
    return payload


def validate_source(raw: Any) -> dict[str, Any]:
    data = _require_mapping(raw, "source")
    _require_version(data, SOURCE_SCHEMA_VERSION, "source")
    payload = dict(data)
    payload.update(
        {
            "asset": _normalize_asset(data.get("asset"), path="source.asset"),
            "kind": validate_source_kind(data.get("kind"), path="source.kind"),
            "metadata": _optional_mapping(data.get("metadata", {}), "source.metadata"),
            "project_slug": validate_project_slug(_require_string(data.get("project_slug"), "source.project_slug")),
            "schema_version": SOURCE_SCHEMA_VERSION,
            "source_id": validate_source_id(_require_string(data.get("source_id"), "source.source_id")),
        }
    )
    payload.setdefault("created_at", utc_now_iso())
    payload.setdefault("updated_at", payload["created_at"])
    return payload


def validate_run_record(raw: Any) -> dict[str, Any]:
    data = _require_mapping(raw, "run")
    _require_version(data, RUN_SCHEMA_VERSION, "run")
    status = _require_string(data.get("status"), "run.status")
    if status not in RUN_STATUSES:
        raise ProjectValidationError(f"run.status must be one of {sorted(RUN_STATUSES)}")
    payload = dict(data)
    payload.update(
        {
            "artifacts": _optional_mapping(data.get("artifacts", {}), "run.artifacts"),
            "metadata": _optional_mapping(data.get("metadata", {}), "run.metadata"),
            "project_slug": validate_project_slug(_require_string(data.get("project_slug"), "run.project_slug")),
            "run_id": validate_run_id(_require_string(data.get("run_id"), "run.run_id")),
            "schema_version": RUN_SCHEMA_VERSION,
            "status": status,
        }
    )
    if "argv" in payload:
        argv = payload["argv"]
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise ProjectValidationError("run.argv must be a list of strings")
    payload.setdefault("created_at", utc_now_iso())
    payload.setdefault("updated_at", payload["created_at"])
    return payload


def validate_source_kind(raw: Any, *, path: str = "source.kind") -> str:
    kind = _require_string(raw, path)
    if kind not in SOURCE_KINDS:
        raise ProjectValidationError(f"{path} must be one of {sorted(SOURCE_KINDS)}")
    return kind


def _infer_source_kind(asset: dict[str, Any]) -> str:
    asset_type = asset.get("type")
    if isinstance(asset_type, str):
        if asset_type.startswith("video/"):
            return "video"
        if asset_type.startswith("audio/"):
            return "audio"
        if asset_type.startswith("image/"):
            return "image"
    return "other"


def _normalize_asset(raw: Any, *, path: str) -> dict[str, Any]:
    data = _require_mapping(raw, path)
    has_file = isinstance(data.get("file"), str) and bool(data.get("file"))
    has_url = isinstance(data.get("url"), str) and bool(data.get("url"))
    if has_file == has_url:
        raise ProjectValidationError(f"{path} must contain exactly one of file or url")
    payload = dict(data)
    if has_file:
        payload["file"] = str(Path(payload["file"]).expanduser().resolve())
        payload.pop("url", None)
    else:
        payload["url"] = payload["url"]
        payload.pop("file", None)
    return payload


def _require_version(data: dict[str, Any], expected: int, path: str) -> None:
    if data.get("schema_version") != expected:
        raise ProjectValidationError(f"{path}.schema_version must be {expected}")


def _require_mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ProjectValidationError(f"{path} must be an object")
    return raw


def _optional_mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ProjectValidationError(f"{path} must be an object")
    return dict(raw)


def _require_string(raw: Any, path: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ProjectValidationError(f"{path} must be a non-empty string")
    return raw


def _require_number(raw: Any, path: str) -> int | float:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise ProjectValidationError(f"{path} must be a number")
    return raw
