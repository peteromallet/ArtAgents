"""Project run lifecycle helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from artagents.core.task import env as task_env
from artagents.core.task.plan import step_dir_for
from artagents.threads.ids import generate_run_id

from . import paths
from .jsonio import read_json, write_json_atomic
from .project import require_project
from .schema import build_run_record, utc_now_iso, validate_run_record

PROJECT_RUN_ENV = "ARTAGENTS_PROJECT_RUN"
SENSITIVE_ARG_NAMES = {
    "--api-key",
    "--apikey",
    "--auth",
    "--env-file",
    "--key",
    "--password",
    "--secret",
    "--token",
}
HYPE_ARTIFACTS = {
    "timeline": ("hype.timeline.json", "timeline.json"),
    "assets": ("hype.assets.json", "assets.json"),
    "metadata": ("hype.metadata.json", "metadata.json"),
}


class ProjectRunError(RuntimeError):
    """Raised when a project run cannot be prepared or finalized."""


@dataclass(frozen=True)
class ProjectRunContext:
    project_slug: str
    run_id: str
    run_root: Path
    run_json_path: Path
    record: dict[str, Any]
    root: Path


def reject_project_with_out(project: str | None, out: str | Path | None) -> None:
    if project and out not in (None, ""):
        raise ProjectRunError("--project cannot be combined with --out; project runs own their output directory")


def project_thread_env() -> dict[str, str]:
    return {PROJECT_RUN_ENV: "1"}


def prepare_project_run(
    project_slug: str,
    *,
    tool_id: str | None = None,
    kind: str | None = None,
    argv: Iterable[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    root: str | Path | None = None,
    run_id: str | None = None,
) -> ProjectRunContext:
    require_project(project_slug, root=root)
    projects_root = paths.resolve_projects_root(root)
    parent_run_id = task_env.task_run_id_env()
    if parent_run_id:
        task_project = task_env.task_project_env()
        if task_project != project_slug:
            raise ProjectRunError(f"task run is bound to project {task_project!r}, refusing to prepare run for {project_slug!r}")
        step_id = task_env.task_step_id_env()
        if not step_id:
            raise ProjectRunError("ARTAGENTS_TASK_STEP_ID must be set when ARTAGENTS_TASK_RUN_ID is set")
        run_root = step_dir_for(project_slug, parent_run_id, step_id, root=projects_root)
        run_root.mkdir(parents=True, exist_ok=True)
        now = utc_now_iso()
        run_metadata = dict(metadata or {})
        run_metadata.update({"attached_to_task_run": True, "task_step_id": step_id})
        record: dict[str, Any] = {
            "artifacts": {},
            "created_at": now,
            "metadata": run_metadata,
            "out": str(run_root),
            "project_slug": project_slug,
            "run_id": parent_run_id,
            "schema_version": 1,
            "status": "attached",
            "updated_at": now,
        }
        if tool_id is not None:
            record["tool_id"] = tool_id
        if kind is not None:
            record["kind"] = kind
        if argv is not None:
            record["argv"] = redact_cli_args(list(argv))
        return ProjectRunContext(
            project_slug=project_slug,
            run_id=parent_run_id,
            run_root=run_root,
            run_json_path=run_root / "run.json",
            record=record,
            root=projects_root,
        )
    effective_run_id = paths.validate_run_id(run_id or generate_run_id())
    run_root = paths.run_dir(project_slug, effective_run_id, root=projects_root)
    if run_root.exists() and any(run_root.iterdir()):
        raise ProjectRunError(f"project run directory already exists: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    record = build_run_record(
        project_slug,
        effective_run_id,
        tool_id=tool_id,
        kind=kind,
        status="prepared",
        out=run_root,
        argv=redact_cli_args(list(argv or ())),
        metadata=dict(metadata or {}),
    )
    run_json_path = paths.run_json_path(project_slug, effective_run_id, root=projects_root)
    write_json_atomic(run_json_path, record)
    return ProjectRunContext(
        project_slug=project_slug,
        run_id=effective_run_id,
        run_root=run_root,
        run_json_path=run_json_path,
        record=record,
        root=projects_root,
    )


def finalize_project_run(
    context: ProjectRunContext,
    *,
    status: str,
    returncode: int | None = None,
    error: BaseException | str | None = None,
    metadata: Mapping[str, Any] | None = None,
    brief_slug: str | None = None,
    artifact_roots: Iterable[str | Path] = (),
) -> dict[str, Any]:
    record = dict(context.record)
    merged_metadata = dict(record.get("metadata", {}))
    if metadata:
        merged_metadata.update(dict(metadata))
    if returncode is not None:
        merged_metadata["returncode"] = returncode
    if error is not None:
        merged_metadata["error"] = str(error)
    record["metadata"] = merged_metadata
    attached_to_task_run = bool(merged_metadata.get("attached_to_task_run"))
    record["status"] = _normalize_status(status, returncode=returncode)
    record["updated_at"] = utc_now_iso()
    artifacts = dict(record.get("artifacts", {}))
    mirror_dest = context.run_root / "produces" if attached_to_task_run else None
    artifacts.update(
        mirror_hype_artifacts(context.run_root, brief_slug=brief_slug, artifact_roots=artifact_roots, dest_root=mirror_dest)
    )
    record["artifacts"] = artifacts
    normalized = validate_run_record(record)
    if not attached_to_task_run:
        write_json_atomic(context.run_json_path, normalized)
    context.record.clear()
    context.record.update(normalized)
    return normalized


def write_run_record(
    project_slug: str,
    run_id: str,
    *,
    root: str | Path | None = None,
    **fields: Any,
) -> dict[str, Any]:
    require_project(project_slug, root=root)
    run_root = paths.run_dir(project_slug, run_id, root=root)
    run_root.mkdir(parents=True, exist_ok=True)
    if "argv" in fields and fields["argv"] is not None:
        fields["argv"] = redact_cli_args(list(fields["argv"]))
    payload = build_run_record(project_slug, run_id, out=run_root, **fields)
    write_json_atomic(paths.run_json_path(project_slug, run_id, root=root), payload)
    return payload


def load_run_record(project_slug: str, run_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    return validate_run_record(read_json(paths.run_json_path(project_slug, run_id, root=root)))


def require_run_record(project_slug: str, run_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    run_path = paths.run_json_path(project_slug, run_id, root=root)
    if not run_path.exists():
        raise FileNotFoundError(f"run not found: {run_id}. Next command: python3 -m artagents projects show --project {project_slug}")
    return validate_run_record(read_json(run_path))


def update_run_record(project_slug: str, run_id: str, updates: dict[str, Any], *, root: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(updates, dict):
        raise TypeError("run updates must be an object")
    payload = require_run_record(project_slug, run_id, root=root)
    payload.update(updates)
    payload["updated_at"] = utc_now_iso()
    if "argv" in payload and payload["argv"] is not None:
        payload["argv"] = redact_cli_args(list(payload["argv"]))
    normalized = validate_run_record(payload)
    write_json_atomic(paths.run_json_path(project_slug, run_id, root=root), normalized)
    return normalized


def redact_cli_args(argv: Iterable[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for raw in argv:
        arg = str(raw)
        if hide_next:
            redacted.append("<redacted>")
            hide_next = False
            continue
        if "=" in arg:
            key, _value = arg.split("=", 1)
            if _is_sensitive_key(key):
                redacted.append(f"{key}=<redacted>")
                continue
        if _is_sensitive_key(arg):
            redacted.append(arg)
            hide_next = True
            continue
        redacted.append(arg)
    return redacted


def mirror_hype_artifacts(
    run_root: str | Path,
    *,
    brief_slug: str | None = None,
    artifact_roots: Iterable[str | Path] = (),
    dest_root: str | Path | None = None,
) -> dict[str, Any]:
    run_path = Path(run_root).expanduser().resolve()
    source = discover_hype_artifact_root(run_path, brief_slug=brief_slug, artifact_roots=artifact_roots)
    if source is None:
        return {}
    dest_path_root = Path(dest_root).expanduser().resolve() if dest_root is not None else run_path
    dest_path_root.mkdir(parents=True, exist_ok=True)
    mirrored: dict[str, Any] = {}
    for key, (source_name, dest_name) in HYPE_ARTIFACTS.items():
        source_path = source / source_name
        dest_path = dest_path_root / dest_name
        shutil.copy2(source_path, dest_path)
        mirrored[key] = {"path": str(dest_path), "source_path": str(source_path)}
    return mirrored


def discover_hype_artifact_root(
    run_root: str | Path,
    *,
    brief_slug: str | None = None,
    artifact_roots: Iterable[str | Path] = (),
) -> Path | None:
    run_path = Path(run_root).expanduser().resolve()
    candidates = [Path(item).expanduser().resolve() for item in artifact_roots]
    candidates.append(run_path)
    if brief_slug:
        candidates.append(run_path / "briefs" / brief_slug)
    for candidate in candidates:
        if _has_hype_artifact_set(candidate):
            return candidate
    briefs_root = run_path / "briefs"
    if not briefs_root.is_dir():
        return None
    matches = sorted(path for path in briefs_root.iterdir() if path.is_dir() and _has_hype_artifact_set(path))
    if len(matches) > 1:
        raise ProjectRunError(
            "multiple nested hype artifact sets found; pass brief_slug so ArtAgents can choose one deterministically"
        )
    return matches[0] if matches else None


def _normalize_status(status: str, *, returncode: int | None) -> str:
    if status == "success" and returncode not in (None, 0):
        return "failed"
    if status in {"success", "failed", "skipped", "error", "prepared"}:
        return status
    if status in {"succeeded", "ok"}:
        return "success"
    if status in {"skip"}:
        return "skipped"
    if status in {"nonzero"}:
        return "failed"
    if returncode not in (None, 0):
        return "failed"
    raise ProjectRunError(f"unsupported project run status: {status}")


def _has_hype_artifact_set(path: Path) -> bool:
    return all((path / source_name).is_file() for source_name, _dest_name in HYPE_ARTIFACTS.values())


def _is_sensitive_key(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in SENSITIVE_ARG_NAMES:
        return True
    return any(token in normalized for token in ("api_key", "apikey", "password", "secret", "token"))


__all__ = [
    "PROJECT_RUN_ENV",
    "ProjectRunContext",
    "ProjectRunError",
    "discover_hype_artifact_root",
    "finalize_project_run",
    "load_run_record",
    "mirror_hype_artifacts",
    "prepare_project_run",
    "project_thread_env",
    "redact_cli_args",
    "reject_project_with_out",
    "require_run_record",
    "update_run_record",
    "write_run_record",
]
