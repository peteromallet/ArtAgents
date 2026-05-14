"""Build and finalize v1 run.json records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

import xxhash

from . import variants
from .ids import generate_run_id, is_ulid
from .provenance import enrich_run_provenance
from .schema import SCHEMA_VERSION, utc_now, validate_run_record

SECRET_KEY_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSPHRASE|API_KEY|BEARER)", re.IGNORECASE)
RUN_RECORD_NAME = "run.json"


def build_run_record(
    *,
    run_id: str | None,
    thread_id: str,
    kind: str,
    executor_id: str | None = None,
    orchestrator_id: str | None = None,
    out_path: Path,
    repo_root: Path,
    inputs: Mapping[str, Any] | None = None,
    brief: Path | str | None = None,
    cli_args: list[str] | None = None,
    parent_run_ids: list[dict[str, Any]] | None = None,
    external_service_calls: list[dict[str, str]] | None = None,
    timeline_id: str | None = None,
) -> dict[str, Any]:
    inputs = dict(inputs or {})
    out_path.mkdir(parents=True, exist_ok=True)
    brief_path = Path(brief).expanduser().resolve() if brief not in (None, "") else None
    brief_hash = sha256_file(brief_path) if brief_path is not None and brief_path.is_file() else None
    snapshot_brief(out_path, brief_path)
    input_artifacts = collect_input_artifacts(inputs=inputs, brief=brief_path, repo_root=repo_root, run_out=out_path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id or generate_run_id(),
        "thread_id": thread_id,
        "parent_run_ids": parent_run_ids or [],
        "executor_id": executor_id,
        "orchestrator_id": orchestrator_id,
        "kind": kind,
        "pid": os.getpid(),
        "status": "running",
        "started_at": utc_now(),
        "ended_at": None,
        "returncode": None,
        "out_path": repo_relative(out_path, repo_root),
        "cli_args_redacted": redact_cli_args(cli_args or []),
        "agent_version": agent_version(repo_root),
        "brief_content_sha256": brief_hash,
        "inputs_digest": inputs_digest(inputs),
        "input_artifacts": input_artifacts,
        "output_artifacts": [],
        "external_service_calls": normalize_external_service_calls(external_service_calls or _calls_from_inputs(inputs)),
        "starred": False,
    }
    if timeline_id is not None:
        payload["timeline_id"] = timeline_id
    return validate_run_record(payload)


def finalize_run_record(
    record: Mapping[str, Any],
    *,
    repo_root: Path,
    out_path: Path,
    returncode: int | None,
    status: str | None = None,
    error: BaseException | str | None = None,
) -> dict[str, Any]:
    updated = dict(record)
    updated["ended_at"] = utc_now()
    updated["returncode"] = returncode
    if status is None:
        status = "succeeded" if returncode in (0, None) else "failed"
    updated["status"] = status
    if error is not None:
        updated["error"] = {
            "type": error.__class__.__name__ if isinstance(error, BaseException) else "runtime",
            "message": str(error),
        }
    updated = enrich_run_provenance(repo_root, out_path, updated)
    updated["output_artifacts"] = collect_output_artifacts(out_path=out_path, repo_root=repo_root)
    return validate_run_record(updated)


def write_run_record(record: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(dict(record), handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def collect_input_artifacts(*, inputs: Mapping[str, Any], brief: Path | None, repo_root: Path, run_out: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[Path] = set()
    if brief is not None:
        _append_artifact(artifacts, brief, repo_root=repo_root, run_out=run_out, kind="brief", seen=seen)
    for key, value in inputs.items():
        if key == "external_service_calls":
            continue
        for candidate in _path_values(value):
            _append_artifact(artifacts, candidate, repo_root=repo_root, run_out=run_out, kind=_kind_for_input(key), seen=seen)
    return artifacts


def collect_output_artifacts(*, out_path: Path, repo_root: Path) -> list[dict[str, Any]]:
    if not out_path.exists() or not out_path.is_dir():
        return []
    artifacts: list[dict[str, Any]] = []
    for path in sorted(item for item in out_path.rglob("*") if item.is_file()):
        if path.name in {RUN_RECORD_NAME, "brief.copy.txt"} or path.name.startswith("."):
            continue
        artifact = _artifact_for_path(path, repo_root=repo_root, run_out=out_path, kind=_kind_for_output(path))
        artifacts.append(artifact)
    return variants.annotate_output_artifacts(artifacts, out_path=out_path, repo_root=repo_root)


def snapshot_brief(out_path: Path, brief_path: Path | None) -> None:
    if brief_path is None or not brief_path.is_file() or _is_private_path(brief_path, out_path):
        return
    target = out_path / "brief.copy.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(brief_path, target)


def redact_cli_args(args: list[str]) -> list[str]:
    redacted: list[str] = []
    for arg in args:
        if arg.startswith("--input=") and "=" in arg.removeprefix("--input="):
            key, value = arg.removeprefix("--input=").split("=", 1)
            redacted.append(f"--input={key}=***REDACTED***" if SECRET_KEY_RE.search(key) else f"--input={key}={value}")
            continue
        if "=" in arg:
            key, value = arg.split("=", 1)
            redacted.append(f"{key}=***REDACTED***" if SECRET_KEY_RE.search(key) else f"{key}={value}")
        elif SECRET_KEY_RE.search(arg):
            redacted.append("***REDACTED***")
        else:
            redacted.append(arg)
    return redacted


def inputs_digest(inputs: Mapping[str, Any]) -> str:
    payload = json.dumps(_jsonable(inputs), sort_keys=True, separators=(",", ":"))
    return xxhash.xxh64_hexdigest(payload.encode("utf-8"))


def normalize_external_service_calls(raw_calls: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for raw in raw_calls:
        if not isinstance(raw, Mapping):
            continue
        call = {key: str(raw[key]) for key in ("model", "model_version", "request_id") if raw.get(key) not in (None, "")}
        if call:
            normalized.append(call)
    return normalized


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_relative(path: Path, repo_root: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        if resolved.exists() and resolved.is_file():
            return f"sha256:{sha256_file(resolved)}"
        raise ValueError(f"path must be under repository root: {resolved}")


def agent_version(repo_root: Path) -> str:
    env_version = os.environ.get("ASTRID_AGENT_VERSION", "").strip()
    if env_version:
        return env_version
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _append_artifact(
    artifacts: list[dict[str, Any]],
    candidate: Path,
    *,
    repo_root: Path,
    run_out: Path,
    kind: str,
    seen: set[Path],
) -> None:
    try:
        resolved = candidate.expanduser().resolve()
    except OSError:
        return
    if resolved in seen or not resolved.is_file():
        return
    seen.add(resolved)
    artifacts.append(_artifact_for_path(resolved, repo_root=repo_root, run_out=run_out, kind=kind))


def _artifact_for_path(path: Path, *, repo_root: Path, run_out: Path, kind: str) -> dict[str, Any]:
    digest = sha256_file(path)
    if _is_private_path(path, run_out):
        return {
            "sha256": digest,
            "kind": kind,
            "role": "other",
            "label": path.name,
            "private": True,
        }
    return {
        "path": repo_relative(path, repo_root),
        "sha256": digest,
        "kind": kind,
        "role": "other",
    }


def _is_private_path(path: Path, run_out: Path) -> bool:
    try:
        path.resolve().relative_to((run_out / "private").resolve())
        return True
    except ValueError:
        return False


def _path_values(value: Any) -> list[Path]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    paths: list[Path] = []
    for item in values:
        if isinstance(item, Path):
            paths.append(item)
        elif isinstance(item, str) and item and "://" not in item:
            paths.append(Path(item))
    return paths


def _kind_for_input(key: str) -> str:
    lowered = key.lower()
    if "brief" in lowered:
        return "brief"
    if "video" in lowered:
        return "video"
    if "audio" in lowered:
        return "audio"
    if "image" in lowered:
        return "image"
    return "input"


def _kind_for_output(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".wav", ".mp3", ".aac", ".m4a"}:
        return "audio"
    if suffix in {".json"}:
        return "metadata"
    if suffix in {".txt", ".md"}:
        return "text"
    return "artifact"


def _calls_from_inputs(inputs: Mapping[str, Any]) -> list[Any]:
    raw = inputs.get("external_service_calls")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, Mapping):
        return [raw]
    return []


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _fsync_dir(path: Path) -> None:
    fd = None
    try:
        fd = os.open(path, getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY)
        os.fsync(fd)
    except OSError:
        pass
    finally:
        if fd is not None:
            os.close(fd)
