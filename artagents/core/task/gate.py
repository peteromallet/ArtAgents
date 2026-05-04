"""Task-run dispatch gate."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from artagents.core.project.paths import project_dir
from artagents.core.task.active_run import read_active_run
from artagents.core.task.env import apply_task_run_env, is_in_task_run
from artagents.core.task.events import (
    append_event,
    make_step_completed_event,
    make_step_dispatched_event,
    read_events,
    verify_chain,
)
from artagents.core.task.plan import compute_plan_hash, load_plan


class TaskRunGateError(RuntimeError):
    """Raised when task-mode dispatch is rejected."""

    def __init__(self, reason: str, recovery: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.recovery = recovery


@dataclass(frozen=True)
class GateDecision:
    active: bool
    run_id: str | None = None
    plan_step_id: str | None = None
    events_path: Path | None = None
    reentry: bool = False


def gate_command(
    slug: str,
    command: str,
    argv: Sequence[str],
    *,
    root: str | Path | None = None,
    reentry: bool = False,
) -> GateDecision:
    active_run = read_active_run(slug, root=root)
    if active_run is None:
        if not is_in_task_run(slug):
            return GateDecision(active=False)
        _reject(slug, "active_run.json is missing", abort=True)

    project_root = project_dir(slug, root=root)
    plan_path = project_root / "plan.json"
    plan_hash = compute_plan_hash(plan_path)
    if plan_hash != active_run["plan_hash"]:
        _reject(slug, "plan.json hash does not match active_run.json pin", abort=True)

    run_id = active_run["run_id"]
    events_path = project_root / "runs" / run_id / "events.jsonl"
    ok, _last_index, error = verify_chain(events_path)
    if not ok:
        _reject(slug, error or "events.jsonl chain integrity check failed", abort=True)

    plan = load_plan(plan_path)
    events = read_events(events_path)
    cursor = sum(1 for event in events if event.get("kind") == "step_completed")
    if cursor >= len(plan.steps):
        _reject(slug, "plan is exhausted", abort=True)

    step = plan.steps[cursor]
    if command != step.command:
        _reject(slug, "incoming command does not match plan[cursor]", abort=False)

    if reentry:
        latest = events[-1] if events else None
        if (
            not isinstance(latest, dict)
            or latest.get("kind") != "step_dispatched"
            or latest.get("plan_step_id") != step.id
            or latest.get("command") != command
        ):
            _reject(slug, "incoming command does not match plan[cursor]", abort=False)
        apply_task_run_env(run_id, slug, step.id)
        return GateDecision(active=True, run_id=run_id, plan_step_id=step.id, events_path=events_path, reentry=True)

    append_event(events_path, make_step_dispatched_event(step.id, command))
    apply_task_run_env(run_id, slug, step.id)
    return GateDecision(active=True, run_id=run_id, plan_step_id=step.id, events_path=events_path, reentry=False)


def record_dispatch_complete(decision: GateDecision, returncode: int) -> None:
    if not decision.active or decision.events_path is None or decision.plan_step_id is None:
        return
    append_event(decision.events_path, make_step_completed_event(decision.plan_step_id, returncode))


def command_for_argv(argv: Sequence[str]) -> str:
    tokens = [str(token) for token in argv]
    if len(tokens) >= 3 and Path(tokens[0]).name.startswith("python") and tokens[1:3] == ["-m", "artagents"]:
        tokens = tokens[3:]
    elif tokens and Path(tokens[0]).name.endswith("artagents"):
        tokens = tokens[1:]
    return " ".join(shlex.quote(token) for token in tokens)


def _reject(slug: str, reason: str, *, abort: bool) -> None:
    verb = "abort" if abort else "next"
    raise TaskRunGateError(reason=reason, recovery=f"artagents {verb} --project {slug}")
