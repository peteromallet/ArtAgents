"""Task plan helpers."""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal, Union

from artagents.core.project.paths import project_dir, validate_project_slug, validate_run_id
from artagents.core.task.events import canonical_event_json


TASK_STEP_KINDS = ("code", "attested", "nested")
STEP_PATH_SEP = "/"


class TaskPlanError(ValueError):
    """Raised when plan.json is malformed."""


@dataclass(frozen=True)
class AckRule:
    kind: Literal["agent", "actor"]


@dataclass(frozen=True)
class CodeStep:
    id: str
    command: str
    kind: Literal["code"] = "code"


@dataclass(frozen=True)
class AttestedStep:
    id: str
    command: str
    instructions: str
    ack: AckRule
    produces: tuple[str, ...] = ()
    kind: Literal["attested"] = "attested"


@dataclass(frozen=True)
class NestedStep:
    id: str
    plan: "TaskPlan"
    kind: Literal["nested"] = "nested"


TaskPlanStep = Union[CodeStep, AttestedStep, NestedStep]


@dataclass(frozen=True)
class TaskPlan:
    plan_id: str
    version: int
    steps: tuple[TaskPlanStep, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "version": self.version,
            "steps": [_step_to_dict(step) for step in self.steps],
        }


def load_plan(plan_path: str | Path) -> TaskPlan:
    payload = _read_plan_payload(plan_path)
    return _validate_plan(payload)


def compute_plan_hash(plan_path: str | Path) -> str:
    payload = _read_plan_payload(plan_path)
    _validate_plan(payload)
    digest = hashlib.sha256(canonical_event_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def step_dir_for(
    slug: str,
    run_id: str,
    plan_step_id: str,
    *,
    root: str | Path | None = None,
) -> Path:
    validate_project_slug(slug)
    validate_run_id(run_id)
    validate_run_id(plan_step_id)
    return project_dir(slug, root=root) / "runs" / run_id / "steps" / plan_step_id


def iter_steps_with_path(plan: TaskPlan) -> Iterator[tuple[tuple[str, ...], TaskPlanStep]]:
    """Yield ``(path, step)`` in pre-order for every step in the plan tree."""

    def _walk(steps: tuple[TaskPlanStep, ...], prefix: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], TaskPlanStep]]:
        for step in steps:
            path = prefix + (step.id,)
            yield path, step
            if isinstance(step, NestedStep):
                yield from _walk(step.plan.steps, path)

    yield from _walk(plan.steps, ())


def _step_to_dict(step: TaskPlanStep) -> dict[str, Any]:
    if isinstance(step, CodeStep):
        return {"id": step.id, "kind": "code", "command": step.command}
    if isinstance(step, AttestedStep):
        out: dict[str, Any] = {
            "id": step.id,
            "kind": "attested",
            "command": step.command,
            "instructions": step.instructions,
            "ack": {"kind": step.ack.kind},
        }
        if step.produces:
            out["produces"] = list(step.produces)
        return out
    if isinstance(step, NestedStep):
        return {
            "id": step.id,
            "kind": "nested",
            "plan": step.plan.to_dict(),
        }
    raise TaskPlanError(f"unknown step type: {type(step)!r}")


def _read_plan_payload(plan_path: str | Path) -> Any:
    path = Path(plan_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise TaskPlanError(f"invalid JSON in {path}: {exc.msg}") from exc
    except OSError as exc:
        raise TaskPlanError(f"failed to read {path}: {exc}") from exc


def _validate_plan(payload: Any, *, _is_root: bool = True) -> TaskPlan:
    if not isinstance(payload, dict):
        raise TaskPlanError("plan must be an object")
    plan_id = payload.get("plan_id")
    version = payload.get("version")
    steps = payload.get("steps")
    if not isinstance(plan_id, str) or not plan_id:
        raise TaskPlanError("plan plan_id must be a non-empty string")
    if version != 1 or isinstance(version, bool):
        raise TaskPlanError("plan version must be 1")
    if not isinstance(steps, list):
        raise TaskPlanError("plan steps must be a list")

    validated_steps: list[TaskPlanStep] = []
    for index, step in enumerate(steps):
        validated_steps.append(_validate_step(step, index))

    plan = TaskPlan(plan_id=plan_id, version=1, steps=tuple(validated_steps))
    if _is_root:
        _assert_unique_paths(plan)
    return plan


def _validate_step(step: Any, index: int) -> TaskPlanStep:
    if not isinstance(step, dict):
        raise TaskPlanError(f"plan steps[{index}] must be an object")
    kind = step.get("kind", "code")
    if kind == "code":
        return _validate_code_step(step, index)
    if kind == "attested":
        return _validate_attested_step(step, index)
    if kind == "nested":
        return _validate_nested_step(step, index)
    raise TaskPlanError(
        f"plan steps[{index}].kind must be one of {TASK_STEP_KINDS}, got {kind!r}"
    )


def _validate_code_step(step: dict[str, Any], index: int) -> CodeStep:
    step_id = step.get("id")
    command = step.get("command")
    if not isinstance(step_id, str) or not step_id:
        raise TaskPlanError(f"plan steps[{index}].id must be a non-empty string")
    if not isinstance(command, str) or not command:
        raise TaskPlanError(f"plan steps[{index}].command must be a non-empty string")
    _reject_orchestrators_run(command, index)
    return CodeStep(id=validate_run_id(step_id), command=command)


def _validate_attested_step(step: dict[str, Any], index: int) -> AttestedStep:
    step_id = step.get("id")
    command = step.get("command")
    instructions = step.get("instructions")
    produces = step.get("produces", [])
    ack = step.get("ack")
    if not isinstance(step_id, str) or not step_id:
        raise TaskPlanError(f"plan steps[{index}].id must be a non-empty string")
    if not isinstance(command, str) or not command:
        raise TaskPlanError(f"plan steps[{index}].command must be a non-empty string")
    if not isinstance(instructions, str) or not instructions:
        raise TaskPlanError(
            f"plan steps[{index}].instructions must be a non-empty string for attested step"
        )
    if not isinstance(produces, list) or not all(isinstance(p, str) and p for p in produces):
        raise TaskPlanError(
            f"plan steps[{index}].produces must be a list of non-empty strings"
        )
    if not isinstance(ack, dict):
        raise TaskPlanError(f"plan steps[{index}].ack must be an object")
    ack_kind = ack.get("kind")
    if ack_kind not in {"agent", "actor"}:
        raise TaskPlanError(
            f"plan steps[{index}].ack.kind must be 'agent' or 'actor', got {ack_kind!r}"
        )
    return AttestedStep(
        id=validate_run_id(step_id),
        command=command,
        instructions=instructions,
        produces=tuple(produces),
        ack=AckRule(kind=ack_kind),
    )


def _validate_nested_step(step: dict[str, Any], index: int) -> NestedStep:
    step_id = step.get("id")
    child_plan = step.get("plan")
    if not isinstance(step_id, str) or not step_id:
        raise TaskPlanError(f"plan steps[{index}].id must be a non-empty string")
    if not isinstance(child_plan, dict):
        raise TaskPlanError(
            f"plan steps[{index}].plan must be a nested plan object"
        )
    nested = _validate_plan(child_plan, _is_root=False)
    return NestedStep(id=validate_run_id(step_id), plan=nested)


def _reject_orchestrators_run(command: str, index: int) -> None:
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise TaskPlanError(
            f"plan steps[{index}].command is not shell-parseable: {exc}"
        ) from exc
    tokens = _strip_artagents_prefix(tokens)
    if len(tokens) >= 2 and tokens[0] == "orchestrators" and tokens[1] == "run":
        raise TaskPlanError(
            "code step argv targets 'artagents orchestrators run'; use a nested step"
        )


def _strip_artagents_prefix(tokens: list[str]) -> list[str]:
    if (
        len(tokens) >= 3
        and Path(tokens[0]).name.startswith("python")
        and tokens[1:3] == ["-m", "artagents"]
    ):
        return tokens[3:]
    if tokens and Path(tokens[0]).name.endswith("artagents"):
        return tokens[1:]
    return tokens


def _assert_unique_paths(plan: TaskPlan) -> None:
    """Reject sibling-id collisions inside any one frame.

    Identical leaf ids in different subtrees are accepted because their full paths differ.
    """

    def _check(steps: tuple[TaskPlanStep, ...], prefix: tuple[str, ...]) -> None:
        seen: set[str] = set()
        for step in steps:
            if step.id in seen:
                location = STEP_PATH_SEP.join(prefix + (step.id,))
                raise TaskPlanError(
                    f"duplicate step id {step.id!r} among siblings at {location!r}"
                )
            seen.add(step.id)
            if isinstance(step, NestedStep):
                _check(step.plan.steps, prefix + (step.id,))

    _check(plan.steps, ())
