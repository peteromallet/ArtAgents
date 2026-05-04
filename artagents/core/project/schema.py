"""Project file schemas and validators."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import validate_placement_id, validate_project_slug, validate_run_id, validate_source_id

PROJECT_SCHEMA_VERSION = 1
TIMELINE_SCHEMA_VERSION = 1
SOURCE_SCHEMA_VERSION = 1
RUN_SCHEMA_VERSION = 1
REF_KINDS = {"source", "run"}
SOURCE_KINDS = {"audio", "image", "other", "video"}
RUN_STATUSES = {"prepared", "success", "failed", "skipped", "error"}


class ProjectValidationError(ValueError):
    """Raised when project state fails validation."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_project(slug: str, *, name: str | None = None, created_at: str | None = None) -> dict[str, Any]:
    now = created_at or utc_now_iso()
    slug = validate_project_slug(slug)
    return {
        "created_at": now,
        "name": name or slug,
        "schema_version": PROJECT_SCHEMA_VERSION,
        "slug": slug,
        "updated_at": now,
    }


def build_project_timeline(slug: str, *, created_at: str | None = None) -> dict[str, Any]:
    now = created_at or utc_now_iso()
    return {
        "created_at": now,
        "placements": [],
        "project_slug": validate_project_slug(slug),
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "tracks": [],
        "updated_at": now,
    }


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


def build_placement(
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
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "at": _require_number(at, "placement.at"),
        "id": validate_placement_id(placement_id),
        "source": validate_reference(source),
        "track": _require_string(track, "placement.track"),
    }
    if from_ is not None:
        payload["from"] = _require_number(from_, "placement.from")
    if to is not None:
        payload["to"] = _require_number(to, "placement.to")
    if entrance is not None:
        payload["entrance"] = deepcopy(entrance)
    if exit is not None:
        payload["exit"] = deepcopy(exit)
    if transition is not None:
        payload["transition"] = deepcopy(transition)
    if effects is not None:
        if not isinstance(effects, list):
            raise ProjectValidationError("placement.effects must be a list")
        payload["effects"] = deepcopy(effects)
    if params is not None:
        if not isinstance(params, dict):
            raise ProjectValidationError("placement.params must be an object")
        payload["params"] = deepcopy(params)
    return validate_placement(payload)


def source_ref(source_id: str) -> dict[str, str]:
    return {"id": validate_source_id(source_id), "kind": "source"}


def run_ref(run_id: str, clip_id: str) -> dict[str, str]:
    return {"clip_id": _require_string(clip_id, "source.clip_id"), "kind": "run", "run_id": validate_run_id(run_id)}


def validate_project(raw: Any) -> dict[str, Any]:
    data = _require_mapping(raw, "project")
    _require_version(data, PROJECT_SCHEMA_VERSION, "project")
    slug = validate_project_slug(_require_string(data.get("slug"), "project.slug"))
    name = _require_string(data.get("name"), "project.name")
    created_at = _require_string(data.get("created_at"), "project.created_at")
    updated_at = _require_string(data.get("updated_at"), "project.updated_at")
    payload = dict(data)
    payload.update({"created_at": created_at, "name": name, "slug": slug, "updated_at": updated_at})
    return payload


def validate_project_timeline(raw: Any) -> dict[str, Any]:
    data = _require_mapping(raw, "timeline")
    _require_version(data, TIMELINE_SCHEMA_VERSION, "timeline")
    project_slug = validate_project_slug(_require_string(data.get("project_slug"), "timeline.project_slug"))
    placements = data.get("placements")
    if not isinstance(placements, list):
        raise ProjectValidationError("timeline.placements must be a list")
    seen: set[str] = set()
    normalized_placements = []
    for index, placement in enumerate(placements):
        normalized = validate_placement(placement, path=f"timeline.placements[{index}]")
        if normalized["id"] in seen:
            raise ProjectValidationError(f"duplicate placement id: {normalized['id']}")
        seen.add(normalized["id"])
        normalized_placements.append(normalized)
    tracks = data.get("tracks", [])
    if not isinstance(tracks, list):
        raise ProjectValidationError("timeline.tracks must be a list")
    payload = dict(data)
    payload.update(
        {
            "placements": normalized_placements,
            "project_slug": project_slug,
            "schema_version": TIMELINE_SCHEMA_VERSION,
            "tracks": deepcopy(tracks),
        }
    )
    payload.setdefault("created_at", utc_now_iso())
    payload.setdefault("updated_at", payload["created_at"])
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


def validate_placement(raw: Any, *, path: str = "placement") -> dict[str, Any]:
    data = _require_mapping(raw, path)
    payload = dict(data)
    payload["id"] = validate_placement_id(_require_string(data.get("id"), f"{path}.id"))
    payload["track"] = _require_string(data.get("track"), f"{path}.track")
    payload["at"] = _require_number(data.get("at"), f"{path}.at")
    if payload["at"] < 0:
        raise ProjectValidationError(f"{path}.at must be greater than or equal to 0")
    payload["source"] = validate_reference(data.get("source"), path=f"{path}.source")
    if "from" in payload:
        payload["from"] = _require_number(payload["from"], f"{path}.from")
        if payload["from"] < 0:
            raise ProjectValidationError(f"{path}.from must be greater than or equal to 0")
    if "to" in payload:
        payload["to"] = _require_number(payload["to"], f"{path}.to")
        trim_from = payload.get("from", 0)
        if payload["to"] <= trim_from:
            raise ProjectValidationError(f"{path}.to must be greater than {path}.from")
    if "effects" in payload and not isinstance(payload["effects"], list):
        raise ProjectValidationError(f"{path}.effects must be a list")
    if "params" in payload and not isinstance(payload["params"], dict):
        raise ProjectValidationError(f"{path}.params must be an object")
    return payload


def validate_reference(raw: Any, *, path: str = "source") -> dict[str, Any]:
    data = _require_mapping(raw, path)
    kind = _require_string(data.get("kind"), f"{path}.kind")
    if kind not in REF_KINDS:
        raise ProjectValidationError(f"{path}.kind must be one of {sorted(REF_KINDS)}")
    if kind == "source":
        return {"id": validate_source_id(_require_string(data.get("id"), f"{path}.id")), "kind": "source"}
    ref = {"clip_id": _require_string(data.get("clip_id"), f"{path}.clip_id"), "kind": "run", "run_id": validate_run_id(data.get("run_id"))}
    return ref


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
