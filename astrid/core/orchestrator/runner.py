"""Execution helpers for Astrid orchestrator definitions."""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from astrid.contracts.schema import Output
from astrid.core.executor.runner import _has_value, _stringify_value
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

from .registry import OrchestratorRegistry, load_default_registry
from .schema import OrchestratorDefinition, OrchestratorValidationError


_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class OrchestratorRunnerError(OrchestratorValidationError):
    """Raised when a orchestrator cannot be prepared or executed."""


@dataclass(frozen=True)
class OrchestratorRunRequest:
    orchestrator_id: str
    out: Path | str | None = None
    project: str | None = None
    inputs: Mapping[str, Any] = field(default_factory=dict)
    outputs: Mapping[str, Any] = field(default_factory=dict)
    brief: Path | str | None = None
    orchestrator_args: tuple[str, ...] = ()
    dry_run: bool = False
    python_exec: str | None = None
    verbose: bool = False
    thread: str | None = None
    variants: int | None = None
    from_ref: str | None = None


@dataclass(frozen=True)
class OrchestratorRunError:
    message: str
    kind: str = "runtime"

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "message": self.message}


@dataclass(frozen=True)
class OrchestratorPlanStep:
    id: str
    kind: str = "command"
    command: tuple[str, ...] = ()
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "command": list(self.command),
        }
        if self.description:
            payload["description"] = self.description
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class OrchestratorPlan:
    steps: tuple[OrchestratorPlanStep, ...] = ()
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"steps": [step.to_dict() for step in self.steps]}
        if self.summary:
            payload["summary"] = self.summary
        return payload


@dataclass(frozen=True)
class OrchestratorRunResult:
    orchestrator_id: str
    kind: str
    runtime_kind: str
    command: tuple[str, ...] = ()
    planned_commands: tuple[tuple[str, ...], ...] = ()
    cwd: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    returncode: int | None = None
    dry_run: bool = False
    outputs: Mapping[str, Any] = field(default_factory=dict)
    errors: tuple[OrchestratorRunError, ...] = ()
    plan: OrchestratorPlan | None = None

    @property
    def ok(self) -> bool:
        return not self.errors and (self.returncode is None or self.returncode == 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "orchestrator_id": self.orchestrator_id,
            "kind": self.kind,
            "runtime_kind": self.runtime_kind,
            "command": list(self.command),
            "planned_commands": [list(command) for command in self.planned_commands],
            "cwd": self.cwd,
            "env": dict(self.env),
            "returncode": self.returncode,
            "dry_run": self.dry_run,
            "outputs": dict(self.outputs),
            "errors": [error.to_dict() for error in self.errors],
            "plan": self.plan.to_dict() if self.plan is not None else None,
            "ok": self.ok,
        }


def run_orchestrator(request: OrchestratorRunRequest, registry: OrchestratorRegistry | None = None) -> OrchestratorRunResult:
    if request.project and task_env.is_in_task_run(request.project):
        try:
            task_gate.gate_command(
                request.project,
                task_gate.command_for_argv(_request_argv_for_gate(request)),
                [],
                reentry=True,
            )
        except task_gate.TaskRunGateError as exc:
            raise OrchestratorRunnerError(exc.recovery) from exc
    active_registry = registry or load_default_registry()
    orchestrator = active_registry.get(request.orchestrator_id)
    project_context, effective_request = _prepare_project_request(request, orchestrator)
    context = None if project_context is not None else thread_wrapper.begin_orchestrator_run(effective_request, orchestrator)
    try:
        result = _run_orchestrator_inner(effective_request, orchestrator)
    except Exception as exc:
        thread_wrapper.finalize_exception(context, exc)
        if project_context is not None:
            _finalize_project_orchestrator(project_context, effective_request, status="error", returncode=-1, error=exc)
        raise
    thread_wrapper.finalize_result(context, result)
    if project_context is not None:
        _finalize_project_orchestrator(
            project_context,
            effective_request,
            status=_project_status_for_result(result),
            returncode=result.returncode,
        )
    return result


def _request_argv_for_gate(request: OrchestratorRunRequest) -> tuple[str, ...]:
    argv = ["orchestrators", "run", request.orchestrator_id, *request.orchestrator_args]
    if request.project:
        argv.extend(["--project", request.project])
    return tuple(argv)


def _run_orchestrator_inner(request: OrchestratorRunRequest, orchestrator: OrchestratorDefinition) -> OrchestratorRunResult:
    values = _request_values(request)
    _validate_out_requirement(orchestrator, request)
    _validate_required_inputs(orchestrator, values)
    if orchestrator.runtime.kind == "python":
        return _ensure_dry_run_plan(_run_python_orchestrator(orchestrator, request))
    if orchestrator.runtime.kind == "command":
        return _ensure_dry_run_plan(_run_command_orchestrator(orchestrator, request, values))
    raise OrchestratorRunnerError(f"unsupported orchestrator runtime kind {orchestrator.runtime.kind!r}")


def build_orchestrator_command(request: OrchestratorRunRequest, registry: OrchestratorRegistry | None = None) -> tuple[str, ...]:
    active_registry = registry or load_default_registry()
    orchestrator = active_registry.get(request.orchestrator_id)
    values = _request_values(request)
    _validate_out_requirement(orchestrator, request)
    _validate_required_inputs(orchestrator, values)
    if orchestrator.runtime.kind != "command":
        raise OrchestratorRunnerError(f"orchestrator {orchestrator.id!r} does not use a command runtime")
    command, _, _ = _expand_command_runtime(orchestrator, request, values)
    return command


def _run_python_orchestrator(orchestrator: OrchestratorDefinition, request: OrchestratorRunRequest) -> OrchestratorRunResult:
    runtime = orchestrator.runtime
    if not runtime.module or not runtime.function:
        raise OrchestratorRunnerError(f"orchestrator {orchestrator.id!r} has an invalid Python runtime")
    try:
        module = importlib.import_module(runtime.module)
    except Exception as exc:
        raise OrchestratorRunnerError(f"failed to import orchestrator runtime module {runtime.module!r}: {exc}") from exc
    target = getattr(module, runtime.function, None)
    if not callable(target):
        raise OrchestratorRunnerError(f"orchestrator runtime target {runtime.module}.{runtime.function} is not callable")
    try:
        raw_result = target(request, orchestrator)
    except OrchestratorRunnerError:
        raise
    except Exception as exc:
        raise OrchestratorRunnerError(f"orchestrator {orchestrator.id!r} Python runtime failed: {exc}") from exc
    return _normalize_python_result(orchestrator, request, raw_result)


def _run_command_orchestrator(
    orchestrator: OrchestratorDefinition,
    request: OrchestratorRunRequest,
    values: Mapping[str, Any],
) -> OrchestratorRunResult:
    command, cwd, env = _expand_command_runtime(orchestrator, request, values)
    if request.dry_run:
        planned_commands = (command,)
        return OrchestratorRunResult(
            orchestrator_id=orchestrator.id,
            kind=orchestrator.kind,
            runtime_kind="command",
            command=command,
            planned_commands=planned_commands,
            cwd=cwd,
            env=env,
            returncode=None,
            dry_run=True,
            plan=_plan_from_commands(planned_commands, prefix=orchestrator.id),
        )
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env={**os.environ, **env, **_project_subprocess_env(request), **thread_wrapper.subprocess_env()},
        check=False,
    )
    return OrchestratorRunResult(
        orchestrator_id=orchestrator.id,
        kind=orchestrator.kind,
        runtime_kind="command",
        command=command,
        planned_commands=(command,),
        cwd=cwd,
        env=env,
        returncode=completed.returncode,
    )


def _expand_command_runtime(
    orchestrator: OrchestratorDefinition,
    request: OrchestratorRunRequest,
    values: Mapping[str, Any],
) -> tuple[tuple[str, ...], str | None, dict[str, str]]:
    command_spec = orchestrator.runtime.command
    if command_spec is None:
        raise OrchestratorRunnerError(f"orchestrator {orchestrator.id!r} has no command runtime")
    placeholders = _placeholder_values(orchestrator, request, values)
    argv: list[str] = []
    for part in command_spec.argv:
        if part == "{orchestrator_args}":
            argv.extend(request.orchestrator_args)
        else:
            argv.append(_expand_placeholders(part, placeholders))
    cwd = _expand_placeholders(command_spec.cwd, placeholders) if command_spec.cwd else None
    env = {key: _expand_placeholders(value, placeholders) for key, value in command_spec.env.items()}
    return tuple(argv), cwd, env


def _normalize_python_result(
    orchestrator: OrchestratorDefinition,
    request: OrchestratorRunRequest,
    raw_result: Any,
) -> OrchestratorRunResult:
    if isinstance(raw_result, OrchestratorRunResult):
        return _ensure_dry_run_plan(raw_result)
    if raw_result is None:
        return _ensure_dry_run_plan(OrchestratorRunResult(
            orchestrator_id=orchestrator.id,
            kind=orchestrator.kind,
            runtime_kind="python",
            returncode=None if request.dry_run else 0,
            dry_run=request.dry_run,
        ))
    if isinstance(raw_result, int):
        return _ensure_dry_run_plan(OrchestratorRunResult(
            orchestrator_id=orchestrator.id,
            kind=orchestrator.kind,
            runtime_kind="python",
            returncode=None if request.dry_run else raw_result,
            dry_run=request.dry_run,
        ))
    if isinstance(raw_result, dict):
        return _result_from_mapping(orchestrator, request, raw_result)
    raise OrchestratorRunnerError(
        f"orchestrator {orchestrator.id!r} returned unsupported result type {type(raw_result).__name__}; "
        "expected OrchestratorRunResult, dict, int, or None"
    )


def _result_from_mapping(
    orchestrator: OrchestratorDefinition,
    request: OrchestratorRunRequest,
    raw: Mapping[str, Any],
) -> OrchestratorRunResult:
    command = _tuple_of_strings(raw.get("command", ()), "command")
    planned_commands = _planned_commands(raw.get("planned_commands", (command,) if command else ()))
    errors = tuple(
        error if isinstance(error, OrchestratorRunError) else OrchestratorRunError(str(error))
        for error in raw.get("errors", ())
    )
    returncode = raw.get("returncode")
    if request.dry_run and returncode is not None:
        returncode = None
    elif returncode is not None:
        returncode = int(returncode)
    plan = _plan_from_raw(raw.get("plan")) if "plan" in raw else None
    return _ensure_dry_run_plan(OrchestratorRunResult(
        orchestrator_id=str(raw.get("orchestrator_id") or orchestrator.id),
        kind=str(raw.get("kind") or orchestrator.kind),
        runtime_kind=str(raw.get("runtime_kind") or "python"),
        command=command,
        planned_commands=planned_commands,
        cwd=_optional_string(raw.get("cwd")),
        env={str(key): str(value) for key, value in dict(raw.get("env", {})).items()},
        returncode=returncode,
        dry_run=bool(raw.get("dry_run", request.dry_run)),
        outputs=dict(raw.get("outputs", {})),
        errors=errors,
        plan=plan,
    ))


def _ensure_dry_run_plan(result: OrchestratorRunResult) -> OrchestratorRunResult:
    if not result.dry_run or result.plan is not None:
        return result
    return replace(result, plan=_plan_from_commands(result.planned_commands, prefix=result.orchestrator_id))


def _plan_from_commands(commands: tuple[tuple[str, ...], ...], *, prefix: str) -> OrchestratorPlan:
    steps = tuple(
        OrchestratorPlanStep(
            id=f"{prefix}.step_{index + 1}",
            kind="command",
            command=command,
        )
        for index, command in enumerate(commands)
    )
    return OrchestratorPlan(steps=steps)


def _plan_from_raw(raw: Any) -> OrchestratorPlan | None:
    if raw is None:
        return None
    if isinstance(raw, OrchestratorPlan):
        return raw
    if not isinstance(raw, Mapping):
        raise OrchestratorRunnerError("plan must be an object")
    raw_steps = raw.get("steps", ())
    if not isinstance(raw_steps, (list, tuple)):
        raise OrchestratorRunnerError("plan.steps must be a list")
    return OrchestratorPlan(
        steps=tuple(_plan_step_from_raw(item, f"plan.steps[{index}]") for index, item in enumerate(raw_steps)),
        summary=str(raw.get("summary") or ""),
    )


def _plan_step_from_raw(raw: Any, path: str) -> OrchestratorPlanStep:
    if isinstance(raw, OrchestratorPlanStep):
        return raw
    if not isinstance(raw, Mapping):
        raise OrchestratorRunnerError(f"{path} must be an object")
    step_id = raw.get("id")
    if not isinstance(step_id, str) or not step_id.strip():
        raise OrchestratorRunnerError(f"{path}.id must be a non-empty string")
    return OrchestratorPlanStep(
        id=step_id,
        kind=str(raw.get("kind") or "command"),
        command=_tuple_of_strings(raw.get("command", ()), f"{path}.command"),
        description=str(raw.get("description") or ""),
        metadata=dict(raw.get("metadata", {})),
    )


def _placeholder_values(orchestrator: OrchestratorDefinition, request: OrchestratorRunRequest, values: Mapping[str, Any]) -> dict[str, str]:
    placeholders: dict[str, str] = {
        "python_exec": str(values.get("python_exec") or request.python_exec or sys.executable),
        "orchestrator_args": " ".join(request.orchestrator_args),
        "verbose": str(bool(values.get("verbose", request.verbose))).lower(),
    }
    if request.out is not None:
        placeholders["out"] = str(Path(request.out).expanduser().resolve())
    brief = values.get("brief") or request.brief
    if brief is not None:
        placeholders["brief"] = str(Path(str(brief)).expanduser().resolve())
    for key, value in values.items():
        if value is None:
            continue
        if key == "verbose":
            placeholders[key] = str(bool(value)).lower()
        else:
            placeholders[key] = _stringify_value(value)
    for output in orchestrator.outputs:
        output_path = _output_value(output, request, placeholders)
        placeholders[output.name] = output_path
        if output.placeholder:
            placeholders[output.placeholder] = output_path
    return placeholders


def _prepare_project_request(
    request: OrchestratorRunRequest,
    orchestrator: OrchestratorDefinition,
) -> tuple[ProjectRunContext | None, OrchestratorRunRequest]:
    if not request.project:
        return None, request
    reject_project_with_out(request.project, request.out)
    if orchestrator.runtime.kind != "command":
        raise OrchestratorRunnerError("--project is currently supported only for command-runtime orchestrators")
    if _orchestrator_requires_output_path(orchestrator) and _has_cli_option(tuple(request.orchestrator_args), "--out"):
        raise OrchestratorRunnerError(
            f"--project cannot be combined with passthrough --out for {orchestrator.id}"
        )
    context = prepare_project_run(
        request.project,
        tool_id=orchestrator.id,
        kind="orchestrator",
        argv=_project_argv(request),
        metadata={"dry_run": bool(request.dry_run)},
    )
    args = tuple(request.orchestrator_args)
    if _orchestrator_requires_output_path(orchestrator):
        args = (*args, "--out", str(context.run_root))
    return context, replace(request, out=context.run_root, orchestrator_args=args)


def _orchestrator_requires_output_path(orchestrator: OrchestratorDefinition) -> bool:
    return bool(orchestrator.metadata.get("requires_output_path"))


def _project_argv(request: OrchestratorRunRequest) -> list[str]:
    argv = ["orchestrators", "run", request.orchestrator_id]
    if request.project:
        argv.extend(["--project", request.project])
    if request.brief:
        argv.extend(["--brief", str(request.brief)])
    for key, value in request.inputs.items():
        argv.extend(["--input", f"{key}={_stringify_value(value)}"])
    if request.dry_run:
        argv.append("--dry-run")
    if request.python_exec:
        argv.extend(["--python-exec", request.python_exec])
    if request.verbose:
        argv.append("--verbose")
    if request.orchestrator_args:
        argv.append("--")
        argv.extend(request.orchestrator_args)
    return argv


def _project_status_for_result(result: OrchestratorRunResult) -> str:
    if result.dry_run:
        return "skipped"
    if not result.ok:
        return "failed"
    return "success"


def _finalize_project_orchestrator(
    context: ProjectRunContext,
    request: OrchestratorRunRequest,
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


def _project_subprocess_env(request: OrchestratorRunRequest) -> dict[str, str]:
    return project_thread_env() if request.project else {}


def _has_cli_option(args: tuple[str, ...], option: str) -> bool:
    return any(arg == option or arg.startswith(f"{option}=") for arg in args)


def _output_value(output: Output, request: OrchestratorRunRequest, placeholders: Mapping[str, str]) -> str:
    if output.name in request.outputs:
        return _stringify_value(request.outputs[output.name])
    if output.placeholder and output.placeholder in request.outputs:
        return _stringify_value(request.outputs[output.placeholder])
    if output.path_template:
        return _expand_placeholders(output.path_template, placeholders)
    if request.out is None:
        raise OrchestratorRunnerError(f"--out is required to derive output {output.name!r}")
    return str((Path(request.out).expanduser().resolve() / output.name).resolve())


def _expand_placeholders(value: str, placeholders: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in placeholders:
            raise OrchestratorRunnerError(f"missing value for placeholder {{{key}}}")
        return placeholders[key]

    return _PLACEHOLDER_RE.sub(replace, value)


def _validate_required_inputs(orchestrator: OrchestratorDefinition, values: Mapping[str, Any]) -> None:
    missing = [
        port.name
        for port in orchestrator.inputs
        if port.required and port.default is None and not _has_value(values.get(port.name))
    ]
    if missing:
        raise OrchestratorRunnerError(f"orchestrator {orchestrator.id!r} missing required input(s): {', '.join(missing)}")


def _validate_out_requirement(orchestrator: OrchestratorDefinition, request: OrchestratorRunRequest) -> None:
    if request.out is not None:
        return
    if _orchestrator_requires_output_path(orchestrator):
        raise OrchestratorRunnerError(f"--out is required for {orchestrator.id}")
    if request.dry_run:
        return
    if orchestrator.runtime.kind == "command" and _command_runtime_requires_out(orchestrator, request):
        raise OrchestratorRunnerError("--out is required for command runtime placeholders")
    raise OrchestratorRunnerError("--out is required for orchestrator execution")


def _command_runtime_requires_out(orchestrator: OrchestratorDefinition, request: OrchestratorRunRequest) -> bool:
    command = orchestrator.runtime.command
    if command is None:
        return False
    values = [*command.argv]
    if command.cwd:
        values.append(command.cwd)
    values.extend(command.env.values())
    if any(_uses_placeholder(value, "out") for value in values):
        return True
    for output in orchestrator.outputs:
        if output.name in request.outputs or (output.placeholder and output.placeholder in request.outputs):
            continue
        if output.path_template is None or _uses_placeholder(output.path_template, "out"):
            return True
    return False


def _uses_placeholder(value: str, placeholder: str) -> bool:
    return placeholder in _PLACEHOLDER_RE.findall(value)


def _request_values(request: OrchestratorRunRequest) -> dict[str, Any]:
    values = dict(request.inputs)
    if request.brief is not None and "brief" not in values:
        values["brief"] = request.brief
    if request.python_exec is not None and "python_exec" not in values:
        values["python_exec"] = request.python_exec
    values.setdefault("verbose", request.verbose)
    return values


def _planned_commands(raw: Any) -> tuple[tuple[str, ...], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise OrchestratorRunnerError("planned_commands must be a list of command lists")
    commands: list[tuple[str, ...]] = []
    for index, item in enumerate(raw):
        commands.append(_tuple_of_strings(item, f"planned_commands[{index}]"))
    return tuple(commands)


def _tuple_of_strings(raw: Any, path: str) -> tuple[str, ...]:
    if raw is None or raw == ():
        return ()
    if not isinstance(raw, (list, tuple)):
        raise OrchestratorRunnerError(f"{path} must be a list")
    result: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            raise OrchestratorRunnerError(f"{path}[{index}] must be a string")
        result.append(item)
    return tuple(result)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


__all__ = [
    "OrchestratorRunError",
    "OrchestratorRunRequest",
    "OrchestratorRunResult",
    "OrchestratorRunnerError",
    "build_orchestrator_command",
    "run_orchestrator",
]
