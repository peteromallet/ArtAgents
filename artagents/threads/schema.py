"""V1 schema helpers for thread-layer persisted JSON."""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping

from .ids import require_ulid

SCHEMA_VERSION = 1
THREAD_STATUSES = {"open", "archived"}
ARTIFACT_ROLES = {"variant", "other"}
PARENT_EDGE_KINDS = {"causal", "chosen"}
CONTENT_ADDRESS_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ThreadSchemaError(ValueError):
    """Raised when persisted thread-layer data violates v1 schema rules."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def empty_threads_index() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "active_thread_id": None,
        "threads": {},
    }


def make_thread_record(
    *,
    thread_id: str,
    label: str,
    status: str = "open",
    created_at: str | None = None,
    updated_at: str | None = None,
    archived_at: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "thread_id": require_ulid(thread_id, "thread_id"),
        "label": _require_nonempty_string(label, "label"),
        "status": _require_status(status),
        "created_at": created_at or now,
        "updated_at": updated_at or now,
        "archived_at": archived_at,
        "run_ids": [],
    }
    return validate_thread_record(record)


def validate_threads_index(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ThreadSchemaError("threads index must be an object")
    _require_schema_version(raw, "threads index")
    threads = raw.get("threads")
    if not isinstance(threads, Mapping):
        raise ThreadSchemaError("threads index must contain object field 'threads'")
    normalized_threads: dict[str, Any] = {}
    for thread_id, thread in threads.items():
        require_ulid(thread_id, "threads key")
        normalized = validate_thread_record(thread)
        if normalized["thread_id"] != thread_id:
            raise ThreadSchemaError("thread record id must match threads key")
        normalized_threads[thread_id] = normalized
    active_thread_id = raw.get("active_thread_id")
    if active_thread_id is not None:
        require_ulid(active_thread_id, "active_thread_id")
        if active_thread_id not in normalized_threads:
            raise ThreadSchemaError("active_thread_id must reference an existing thread")
    return {
        "schema_version": SCHEMA_VERSION,
        "active_thread_id": active_thread_id,
        "threads": normalized_threads,
    }


def validate_thread_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ThreadSchemaError("thread record must be an object")
    _require_schema_version(raw, "thread record")
    thread_id = require_ulid(raw.get("thread_id"), "thread_id")
    label = _require_nonempty_string(raw.get("label"), "label")
    status = _require_status(raw.get("status"))
    run_ids = raw.get("run_ids", [])
    if not isinstance(run_ids, list):
        raise ThreadSchemaError("run_ids must be a list")
    for index, run_id in enumerate(run_ids):
        require_ulid(run_id, f"run_ids[{index}]")
    record = copy.deepcopy(dict(raw))
    record["schema_version"] = SCHEMA_VERSION
    record["thread_id"] = thread_id
    record["label"] = label
    record["status"] = status
    record["run_ids"] = list(run_ids)
    for field in ("created_at", "updated_at"):
        _require_nonempty_string(record.get(field), field)
    if record.get("archived_at") is not None:
        _require_nonempty_string(record.get("archived_at"), "archived_at")
    validate_persisted_paths(record)
    return record


def validate_run_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ThreadSchemaError("run record must be an object")
    _require_schema_version(raw, "run record")
    require_ulid(raw.get("run_id"), "run_id")
    require_ulid(raw.get("thread_id"), "thread_id")
    parent_run_ids = raw.get("parent_run_ids", [])
    if not isinstance(parent_run_ids, list):
        raise ThreadSchemaError("parent_run_ids must be a list")
    for index, edge in enumerate(parent_run_ids):
        validate_parent_edge(edge, f"parent_run_ids[{index}]")
    for artifact_key in ("input_artifacts", "output_artifacts"):
        artifacts = raw.get(artifact_key, [])
        if not isinstance(artifacts, list):
            raise ThreadSchemaError(f"{artifact_key} must be a list")
        for index, artifact in enumerate(artifacts):
            validate_artifact(artifact, f"{artifact_key}[{index}]")
    calls = raw.get("external_service_calls", [])
    if not isinstance(calls, list):
        raise ThreadSchemaError("external_service_calls must be a list")
    for index, call in enumerate(calls):
        validate_external_service_call(call, f"external_service_calls[{index}]")
    validate_persisted_paths(raw)
    return copy.deepcopy(dict(raw))


def validate_parent_edge(raw: object, path: str = "parent_run_ids[]") -> dict[str, Any]:
    if isinstance(raw, str):
        return {"run_id": require_ulid(raw, f"{path}.run_id"), "kind": "causal"}
    if not isinstance(raw, Mapping):
        raise ThreadSchemaError(f"{path} must be an object")
    run_id = require_ulid(raw.get("run_id"), f"{path}.run_id")
    kind = raw.get("kind")
    if kind not in PARENT_EDGE_KINDS:
        raise ThreadSchemaError(f"{path}.kind must be one of {sorted(PARENT_EDGE_KINDS)}")
    edge = {"run_id": run_id, "kind": kind}
    if "group" in raw and raw.get("group") is not None:
        edge["group"] = _require_group_id(raw.get("group"), f"{path}.group")
    return edge


def validate_artifact(raw: object, path: str = "artifact") -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ThreadSchemaError(f"{path} must be an object")
    artifact = copy.deepcopy(dict(raw))
    if "path" in artifact and artifact["path"] is not None:
        artifact["path"] = validate_persisted_path(artifact["path"], f"{path}.path")
    if "sha256" in artifact and artifact["sha256"] is not None:
        _require_sha256(artifact["sha256"], f"{path}.sha256")
    role = artifact.get("role", "other")
    if role not in ARTIFACT_ROLES:
        raise ThreadSchemaError(f"{path}.role must be one of {sorted(ARTIFACT_ROLES)}")
    artifact["role"] = role
    if "group" in artifact and artifact["group"] is not None:
        artifact["group"] = _require_group_id(artifact["group"], f"{path}.group")
    return artifact


def validate_external_service_call(raw: object, path: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ThreadSchemaError(f"{path} must be an object")
    allowed = {"model", "model_version", "request_id"}
    extra = set(raw) - allowed
    if extra:
        raise ThreadSchemaError(f"{path} contains unsupported field(s): {', '.join(sorted(extra))}")
    return {key: str(value) for key, value in raw.items() if value not in (None, "")}


def validate_persisted_paths(raw: object) -> None:
    for path, value in _walk(raw):
        key = path[-1] if path else ""
        if key in {"path", "out_path", "artifact_path"} and value is not None:
            validate_persisted_path(value, ".".join(path))


def validate_persisted_path(value: object, field: str = "path") -> str:
    if not isinstance(value, str) or not value:
        raise ThreadSchemaError(f"{field} must be a non-empty string")
    if CONTENT_ADDRESS_RE.fullmatch(value):
        return value
    if "://" in value:
        raise ThreadSchemaError(f"{field} must be repo-relative or content-addressed")
    posix = PurePosixPath(value)
    if posix.is_absolute() or value.startswith("~"):
        raise ThreadSchemaError(f"{field} must be repo-relative or content-addressed")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise ThreadSchemaError(f"{field} must not contain empty, '.', or '..' segments")
    return value


def _require_schema_version(raw: Mapping[str, Any], label: str) -> None:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ThreadSchemaError(f"{label} must have schema_version {SCHEMA_VERSION}")


def _require_status(value: object) -> str:
    if value not in THREAD_STATUSES:
        raise ThreadSchemaError(f"status must be one of {sorted(THREAD_STATUSES)}")
    return str(value)


def _require_nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ThreadSchemaError(f"{field} must be a non-empty string")
    return value


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ThreadSchemaError(f"{field} must be a lowercase sha256 hex digest")
    return value


def _require_group_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ThreadSchemaError(f"{field} must be a non-empty string")
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value) is None:
        raise ThreadSchemaError(f"{field} contains unsupported characters")
    return value


def _walk(value: object, prefix: tuple[str, ...] = ()):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk(item, (*prefix, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, (*prefix, str(index)))
    else:
        yield prefix, value
