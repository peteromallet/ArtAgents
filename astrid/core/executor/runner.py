"""Execution helpers for Astrid executor definitions."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from astrid.core.task import env as task_env
from astrid.core.task import gate as task_gate
from astrid.core.project.run import (
    ProjectRunContext,
    finalize_project_run,
    prepare_project_run,
    project_thread_env,
    reject_project_with_out,
)
from astrid.threads import wrapper as thread_wrapper

from .install import executor_python_path
from .registry import ExecutorRegistry, load_default_registry
from .schema import ConditionSpec, ExecutorDefinition, ExecutorOutput, ExecutorValidationError


_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ExecutorRunnerError(ExecutorValidationError):
    """Raised when a executor cannot be prepared or executed."""


def _pipeline_module():
    from astrid.packs.builtin.hype import run as pipeline

    return pipeline


def _builtin_steps_by_name() -> Mapping[str, Any]:
    pipeline = _pipeline_module()
    steps = {step.name: step for step in pipeline.build_pool_steps()}
    missing = [name for name in pipeline.STEP_ORDER if name not in steps]
    if missing:
        raise ValueError(f"build_pool_steps() is missing STEP_ORDER entries: {', '.join(missing)}")
    return MappingProxyType(steps)


@dataclass(frozen=True)
class ExecutorRunRequest:
    executor_id: str
    out: Path | str
    project: str | None = None
    inputs: Mapping[str, Any] = field(default_factory=dict)
    outputs: Mapping[str, Any] = field(default_factory=dict)
    brief: Path | str | None = None
    dry_run: bool = False
    check_binaries: bool = False
    python_exec: str | None = None
    verbose: bool = False
    thread: str | None = None
    variants: int | None = None
    from_ref: str | None = None


@dataclass(frozen=True)
class ExecutorRunResult:
    executor_id: str
    kind: str
    command: tuple[str, ...] = ()
    cwd: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    returncode: int | None = None
    dry_run: bool = False
    skipped: bool = False
    skipped_reason: str = ""
    missing_binaries: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.missing_binaries and (self.returncode is None or self.returncode == 0)


def run_executor(request: ExecutorRunRequest, registry: ExecutorRegistry | None = None) -> ExecutorRunResult:
    if request.project and task_env.is_in_task_run(request.project):
        try:
            task_gate.gate_command(
                request.project,
                task_gate.command_for_argv(_request_argv_for_gate(request)),
                [],
                reentry=True,
            )
        except task_gate.TaskRunGateError as exc:
            raise ExecutorRunnerError(exc.recovery) from exc
    active_registry = registry or load_default_registry()
    executor = active_registry.get(request.executor_id)
    project_context, effective_request = _prepare_project_request(request, executor)
    context = None if project_context is not None else thread_wrapper.begin_executor_run(effective_request, executor)
    try:
        result = _run_executor_inner(effective_request, executor)
    except Exception as exc:
        thread_wrapper.finalize_exception(context, exc)
        if project_context is not None:
            _finalize_project_executor(project_context, effective_request, status="error", returncode=-1, error=exc)
        raise
    thread_wrapper.finalize_result(context, result)
    if project_context is not None:
        _finalize_project_executor(
            project_context,
            effective_request,
            status=_project_status_for_result(result),
            returncode=result.returncode,
        )
    return result


def _request_argv_for_gate(request: ExecutorRunRequest) -> tuple[str, ...]:
    argv = ["executors", "run", request.executor_id]
    if request.project:
        argv.extend(["--project", request.project])
    return tuple(argv)


def _run_executor_inner(request: ExecutorRunRequest, executor: ExecutorDefinition) -> ExecutorRunResult:
    if executor.id == "upload.youtube":
        return _run_upload_youtube(request)
    values = _request_values(request)
    _validate_required_inputs(executor, values)
    condition_result = evaluate_conditions(executor, values)
    if condition_result.skipped:
        return ExecutorRunResult(
            executor_id=executor.id,
            kind=executor.kind,
            payload={"executor_id": executor.id, "skipped": True, "skipped_reason": condition_result.reason},
            dry_run=request.dry_run,
            skipped=True,
            skipped_reason=condition_result.reason,
        )

    missing_binaries = check_executor_binaries(executor) if request.check_binaries else ()
    if missing_binaries:
        return ExecutorRunResult(
            executor_id=executor.id,
            kind=executor.kind,
            payload={"executor_id": executor.id, "missing_binaries": list(missing_binaries)},
            dry_run=request.dry_run,
            missing_binaries=missing_binaries,
        )

    if executor.kind == "built_in" and "pipeline_step" in executor.metadata:
        return _run_builtin_executor(executor, request)
    return _run_external_executor(executor, request, values)


def _run_upload_youtube(request: ExecutorRunRequest) -> ExecutorRunResult:
    inputs = dict(request.inputs)
    if request.dry_run:
        return ExecutorRunResult(
            executor_id=request.executor_id,
            kind="built_in",
            dry_run=True,
            payload={"would_run": "upload.youtube", "inputs": inputs},
        )

    from astrid.packs.upload.youtube.src.social_publish import publish_youtube_video

    result = publish_youtube_video(
        video_url=_required_input(inputs, "video_url"),
        title=_required_input(inputs, "title"),
        description=_required_input(inputs, "description"),
        tags=_optional_input(inputs, "tags") or _optional_input(inputs, "tag"),
        privacy_status=str(_optional_input(inputs, "privacy_status") or "private"),
        playlist_id=_optional_input(inputs, "playlist_id"),
        made_for_kids=bool(_optional_input(inputs, "made_for_kids") or False),
    )
    return ExecutorRunResult(executor_id=request.executor_id, kind="built_in", payload=result)


@dataclass(frozen=True)
class ConditionResult:
    skipped: bool = False
    reason: str = ""


def evaluate_conditions(executor: ExecutorDefinition, values: Mapping[str, Any]) -> ConditionResult:
    for condition in executor.conditions:
        result = _evaluate_condition(condition, values)
        if result.skipped:
            return result
    return ConditionResult()


def check_executor_binaries(executor: ExecutorDefinition) -> tuple[str, ...]:
    return tuple(binary for binary in executor.isolation.binaries if shutil.which(binary) is None)


def build_pipeline_context(request: ExecutorRunRequest, executor: ExecutorDefinition | None = None) -> argparse.Namespace:
    pipeline = _pipeline_module()
    values = _request_values(request)
    out = Path(request.out).expanduser().resolve()
    brief = _optional_path(values.get("brief") or request.brief)
    if brief is None:
        brief = (out / "brief.txt").resolve()
    audio_value = values.get("audio")
    video_value = values.get("video")
    video = _optional_asset_path(video_value)
    audio = _optional_asset_path(audio_value if audio_value is not None else video_value)
    env_file = _optional_path(values.get("env_file"))
    theme_raw = values.get("theme")
    theme_explicit = theme_raw is not None
    theme = pipeline._resolve_theme_arg(theme_raw) if theme_explicit else pipeline._resolve_theme_arg(pipeline.WORKSPACE_ROOT / "themes" / "banodoco-default" / "theme.json")
    brief_slug = str(values.get("brief_slug") or _default_brief_slug(brief, out))
    brief_out = (out / "briefs" / brief_slug).resolve()
    skip = _as_string_list(values.get("skip"))
    asset_values = _as_string_list(values.get("asset") or values.get("assets"))
    args = argparse.Namespace(
        audio=audio,
        video=video,
        out=out,
        brief=brief,
        brief_out=brief_out,
        brief_copy=brief_out / "brief.txt",
        skip=skip,
        asset=asset_values,
        asset_pairs=_parse_asset_pairs(asset_values),
        primary_asset=values.get("primary_asset"),
        theme=theme,
        theme_explicit=theme_explicit,
        source_slug=str(values.get("source_slug") or out.name),
        brief_slug=brief_slug,
        env_file=env_file,
        extra_args=_normalize_extra_args(values.get("extra_args")),
        target_duration=_optional_float(values.get("target_duration")),
        python_exec=str(values.get("python_exec") or request.python_exec or sys.executable),
        render=bool(values.get("render", False)),
        verbose=bool(values.get("verbose", request.verbose)),
        no_prefetch=bool(values.get("no_prefetch", False)),
        keep_downloads=bool(values.get("keep_downloads", False)),
        cache_dir=_optional_path(values.get("cache_dir")),
        drift=str(values.get("drift") or "strict"),
        from_step=values.get("from_step"),
        max_editor_passes=int(values.get("max_editor_passes", 2)),
        editor_iteration=int(values.get("editor_iteration", 1)),
    )
    if executor is not None:
        args.executor_id = executor.id
    return args


def build_executor_command(request: ExecutorRunRequest, registry: ExecutorRegistry | None = None) -> tuple[str, ...]:
    active_registry = registry or load_default_registry()
    executor = active_registry.get(request.executor_id)
    values = _request_values(request)
    _validate_required_inputs(executor, values)
    condition_result = evaluate_conditions(executor, values)
    if condition_result.skipped:
        return ()
    if executor.kind == "built_in" and "pipeline_step" in executor.metadata:
        step = _step_for_executor(executor)
        args = build_pipeline_context(request, executor)
        return tuple(step.build_cmd(args))
    return _expand_external_command(executor, request, values)[0]


def _run_builtin_executor(executor: ExecutorDefinition, request: ExecutorRunRequest) -> ExecutorRunResult:
    pipeline = _pipeline_module()
    step = _step_for_executor(executor)
    args = build_pipeline_context(request, executor)
    command = tuple(step.build_cmd(args))
    if request.dry_run:
        return ExecutorRunResult(
            executor_id=executor.id,
            kind=executor.kind,
            command=command,
            payload={"executor_id": executor.id, "missing_binaries": [], "returncode": None, "skipped": False, "skipped_reason": ""},
            dry_run=True,
        )
    if args.brief.exists():
        pipeline.prepare_brief_artifacts(args)
    returncode = pipeline.run_step(step, list(command), args)
    return ExecutorRunResult(
        executor_id=executor.id,
        kind=executor.kind,
        command=command,
        payload={"executor_id": executor.id, "missing_binaries": [], "returncode": returncode, "skipped": False, "skipped_reason": ""},
        returncode=returncode,
    )


def _run_external_executor(executor: ExecutorDefinition, request: ExecutorRunRequest, values: Mapping[str, Any]) -> ExecutorRunResult:
    command, cwd, env = _expand_external_command(executor, request, values)
    if request.dry_run:
        return ExecutorRunResult(
            executor_id=executor.id,
            kind=executor.kind,
            command=command,
            cwd=cwd,
            env=env,
            payload={"executor_id": executor.id, "missing_binaries": [], "returncode": None, "skipped": False, "skipped_reason": ""},
            dry_run=True,
        )
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env={**os.environ, **env, **_project_subprocess_env(request), **thread_wrapper.subprocess_env()},
        check=False,
    )
    return ExecutorRunResult(
        executor_id=executor.id,
        kind=executor.kind,
        command=command,
        cwd=cwd,
        env=env,
        payload={
            "executor_id": executor.id,
            "missing_binaries": [],
            "returncode": completed.returncode,
            "skipped": False,
            "skipped_reason": "",
        },
        returncode=completed.returncode,
    )


def _expand_external_command(
    executor: ExecutorDefinition,
    request: ExecutorRunRequest,
    values: Mapping[str, Any],
) -> tuple[tuple[str, ...], str | None, dict[str, str]]:
    if executor.command is None:
        raise ExecutorRunnerError(f"executor {executor.id!r} has no command")
    placeholders = _placeholder_values(executor, request, values)
    argv = tuple(_expand_placeholders(part, placeholders) for part in executor.command.argv)
    cwd = _expand_placeholders(executor.command.cwd, placeholders) if executor.command.cwd else None
    env = {key: _expand_placeholders(value, placeholders) for key, value in executor.command.env.items()}
    return argv, cwd, env


def _prepare_project_request(
    request: ExecutorRunRequest,
    executor: ExecutorDefinition,
) -> tuple[ProjectRunContext | None, ExecutorRunRequest]:
    if not request.project:
        return None, request
    reject_project_with_out(request.project, request.out)
    context = prepare_project_run(
        request.project,
        tool_id=executor.id,
        kind="executor",
        argv=_project_argv(request),
        metadata={"dry_run": bool(request.dry_run)},
    )
    return context, replace(request, out=context.run_root)


def _project_argv(request: ExecutorRunRequest) -> list[str]:
    argv = ["executors", "run", request.executor_id]
    if request.project:
        argv.extend(["--project", request.project])
    if request.brief:
        argv.extend(["--brief", str(request.brief)])
    for key, value in request.inputs.items():
        argv.extend(["--input", f"{key}={_stringify_value(value)}"])
    if request.dry_run:
        argv.append("--dry-run")
    if request.check_binaries:
        argv.append("--check-binaries")
    if request.python_exec:
        argv.extend(["--python-exec", request.python_exec])
    if request.verbose:
        argv.append("--verbose")
    return argv


def _project_status_for_result(result: ExecutorRunResult) -> str:
    if result.skipped or result.dry_run:
        return "skipped"
    if not result.ok:
        return "failed"
    return "success"


def _finalize_project_executor(
    context: ProjectRunContext,
    request: ExecutorRunRequest,
    *,
    status: str,
    returncode: int | None,
    error: BaseException | str | None = None,
) -> None:
    metadata = {"dry_run": bool(request.dry_run)}
    finalize_project_run(
        context,
        status=status,
        returncode=returncode,
        error=error,
        metadata=metadata,
        artifact_roots=[context.run_root],
    )


def _project_subprocess_env(request: ExecutorRunRequest) -> dict[str, str]:
    return project_thread_env() if request.project else {}


def _placeholder_values(executor: ExecutorDefinition, request: ExecutorRunRequest, values: Mapping[str, Any]) -> dict[str, str]:
    out = Path(request.out).expanduser().resolve()
    placeholders: dict[str, str] = {
        "out": str(out),
    }
    python_exec = _resolve_python_exec(executor, request, values)
    if python_exec is not None:
        placeholders["python_exec"] = python_exec
    brief = values.get("brief") or request.brief
    if brief is not None:
        brief_path = Path(str(brief)).expanduser().resolve()
        placeholders["brief"] = str(brief_path)
        brief_slug = str(values.get("brief_slug") or _default_brief_slug(brief_path, out))
        brief_out = out / "briefs" / brief_slug
        placeholders["brief_slug"] = brief_slug
        placeholders["brief_out"] = str(brief_out)
        placeholders["brief_copy"] = str(brief_out / "brief.txt")
    for port in executor.inputs:
        if port.default is not None and port.name not in values:
            placeholders[port.name] = _stringify_value(port.default)
    for key, value in values.items():
        if value is None:
            continue
        placeholders[key] = _stringify_value(value)
    for output in executor.outputs:
        output_path = _output_value(output, request, placeholders)
        placeholders[output.name] = output_path
        if output.placeholder:
            placeholders[output.placeholder] = output_path
    return placeholders


def _output_value(output: ExecutorOutput, request: ExecutorRunRequest, placeholders: Mapping[str, str]) -> str:
    if output.name in request.outputs:
        return _stringify_value(request.outputs[output.name])
    if output.placeholder and output.placeholder in request.outputs:
        return _stringify_value(request.outputs[output.placeholder])
    if output.path_template:
        return _expand_placeholders(output.path_template, placeholders)
    return str((Path(request.out).expanduser().resolve() / output.name).resolve())


def _resolve_python_exec(executor: ExecutorDefinition, request: ExecutorRunRequest, values: Mapping[str, Any]) -> str | None:
    input_override = values.get("python_exec")
    if _has_value(input_override):
        return str(input_override)
    if _has_value(request.python_exec):
        return str(request.python_exec)
    if not _executor_uses_placeholder(executor, "python_exec"):
        return None
    if executor.kind == "external" and executor.isolation.mode == "subprocess":
        installed_python = executor_python_path(executor)
        if installed_python.is_file():
            return str(installed_python)
        raise ExecutorRunnerError(
            f"executor {executor.id!r} requires an installed Python environment; "
            f"run `python3 -m astrid executors install {executor.id}` or pass python_exec as an input override"
        )
    return sys.executable


def _executor_uses_placeholder(executor: ExecutorDefinition, placeholder: str) -> bool:
    if executor.command is None:
        return False
    needle = f"{{{placeholder}}}"
    if any(needle in part for part in executor.command.argv):
        return True
    if executor.command.cwd and needle in executor.command.cwd:
        return True
    return any(needle in value for value in executor.command.env.values())


def _expand_placeholders(value: str, placeholders: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in placeholders:
            raise ExecutorRunnerError(f"missing value for placeholder {{{key}}}")
        return placeholders[key]

    return _PLACEHOLDER_RE.sub(replace, value)


def _validate_required_inputs(executor: ExecutorDefinition, values: Mapping[str, Any]) -> None:
    missing = [
        port.name
        for port in executor.inputs
        if port.required and port.default is None and not _has_value(values.get(port.name))
    ]
    if missing:
        raise ExecutorRunnerError(f"executor {executor.id!r} missing required input(s): {', '.join(missing)}")


def _evaluate_condition(condition: ConditionSpec, values: Mapping[str, Any]) -> ConditionResult:
    if condition.kind == "always":
        return ConditionResult()
    if condition.kind == "requires_input":
        if not condition.input or not _has_value(values.get(condition.input)):
            raise ExecutorRunnerError(f"condition requires input {condition.input!r}")
        return ConditionResult()
    if condition.kind == "requires_file":
        candidate = values.get(condition.input) if condition.input else condition.path
        if not _has_value(candidate):
            raise ExecutorRunnerError("condition requires a file path")
        path = Path(str(candidate)).expanduser()
        if not path.is_file():
            raise ExecutorRunnerError(f"condition requires file: {path}")
        return ConditionResult()
    if condition.kind == "skip_if_input" and condition.input and _has_value(values.get(condition.input)):
        return ConditionResult(skipped=True, reason=f"input {condition.input!r} is set")
    raise ExecutorRunnerError(f"unsupported condition kind {condition.kind!r}")


def _step_for_executor(executor: ExecutorDefinition) -> Any:
    step_name = executor.metadata.get("pipeline_step")
    if not isinstance(step_name, str):
        raise ExecutorRunnerError(f"built-in executor {executor.id!r} is missing metadata.pipeline_step")
    steps = _builtin_steps_by_name()
    if step_name not in steps:
        raise ExecutorRunnerError(f"built-in executor {executor.id!r} references unknown pipeline step {step_name!r}")
    return steps[step_name]


def _request_values(request: ExecutorRunRequest) -> dict[str, Any]:
    values = dict(request.inputs)
    if request.brief is not None and "brief" not in values:
        values["brief"] = request.brief
    if request.python_exec is not None and "python_exec" not in values:
        values["python_exec"] = request.python_exec
    values.setdefault("verbose", request.verbose)
    return values


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


def _optional_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value)).expanduser().resolve()


def _optional_asset_path(value: Any) -> Path | str | None:
    if value is None or value == "":
        return None
    text = str(value)
    pipeline = _pipeline_module()
    if pipeline.asset_cache.is_url(text):
        return text
    return Path(text).expanduser().resolve()


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _as_string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _parse_asset_pairs(values: list[str]) -> list[tuple[str, Path | str]]:
    pairs: list[tuple[str, Path | str]] = []
    for raw in values:
        if "=" not in raw:
            raise ExecutorRunnerError(f"invalid asset value {raw!r}; expected KEY=PATH")
        key, path_text = raw.split("=", 1)
        key = key.strip()
        path_text = path_text.strip()
        if not key or not path_text:
            raise ExecutorRunnerError(f"invalid asset value {raw!r}; expected KEY=PATH")
        pipeline = _pipeline_module()
        if pipeline.asset_cache.is_url(path_text):
            pairs.append((key, path_text))
        else:
            pairs.append((key, Path(path_text).expanduser().resolve()))
    return pairs


def _normalize_extra_args(value: Any) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ExecutorRunnerError("extra_args must be an object keyed by step name")
    return {str(key): _as_string_list(raw_values) for key, raw_values in value.items()}


def _default_brief_slug(brief: Path, out: Path) -> str:
    generic_brief_names = {"brief", "plan", "prompt"}
    return out.name if brief.stem.lower() in generic_brief_names else brief.stem


def _stringify_value(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def _required_input(inputs: Mapping[str, Any], key: str) -> str:
    value = inputs.get(key)
    if value in (None, ""):
        raise ExecutorRunnerError(f"{key} is required")
    return str(value)


def _optional_input(inputs: Mapping[str, Any], key: str) -> Any:
    value = inputs.get(key)
    if value in (None, ""):
        return None
    return value


__all__ = [
    "ConditionResult",
    "ExecutorRunRequest",
    "ExecutorRunResult",
    "ExecutorRunnerError",
    "build_pipeline_context",
    "build_executor_command",
    "check_executor_binaries",
    "evaluate_conditions",
    "run_executor",
]
