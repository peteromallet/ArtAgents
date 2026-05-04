"""Task plan helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artagents.core.project.paths import project_dir, validate_project_slug, validate_run_id
from artagents.core.task.events import canonical_event_json


class TaskPlanError(ValueError):
    """Raised when plan.json is malformed."""


@dataclass(frozen=True)
class TaskPlanStep:
    id: str
    command: str


@dataclass(frozen=True)
class TaskPlan:
    plan_id: str
    version: int
    steps: tuple[TaskPlanStep, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "version": self.version,
            "steps": [{"id": step.id, "command": step.command} for step in self.steps],
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


def _validate_plan(payload: Any) -> TaskPlan:
    if not isinstance(payload, dict):
        raise TaskPlanError("plan.json must be an object")
    plan_id = payload.get("plan_id")
    version = payload.get("version")
    steps = payload.get("steps")
    if not isinstance(plan_id, str) or not plan_id:
        raise TaskPlanError("plan.json plan_id must be a non-empty string")
    if version != 1 or isinstance(version, bool):
        raise TaskPlanError("plan.json version must be 1")
    if not isinstance(steps, list):
        raise TaskPlanError("plan.json steps must be a list")

    validated_steps: list[TaskPlanStep] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise TaskPlanError(f"plan.json steps[{index}] must be an object")
        step_id = step.get("id")
        command = step.get("command")
        if not isinstance(step_id, str) or not step_id:
            raise TaskPlanError(f"plan.json steps[{index}].id must be a non-empty string")
        if not isinstance(command, str) or not command:
            raise TaskPlanError(f"plan.json steps[{index}].command must be a non-empty string")
        validated_steps.append(TaskPlanStep(id=validate_run_id(step_id), command=command))
    return TaskPlan(plan_id=plan_id, version=1, steps=tuple(validated_steps))
