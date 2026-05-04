"""Task-mode kernel APIs."""

from .active_run import clear_active_run, read_active_run, write_active_run
from .env import (
    apply_task_run_env,
    child_subprocess_env,
    is_in_task_run,
    task_project_env,
    task_run_id_env,
    task_step_id_env,
)
from .events import (
    append_event,
    canonical_event_json,
    make_run_started_event,
    make_step_completed_event,
    make_step_dispatched_event,
    read_events,
    verify_chain,
)
from .gate import GateDecision, TaskRunGateError, command_for_argv, gate_command, record_dispatch_complete
from .plan import compute_plan_hash, load_plan, step_dir_for

__all__ = [
    "GateDecision",
    "TaskRunGateError",
    "append_event",
    "apply_task_run_env",
    "canonical_event_json",
    "child_subprocess_env",
    "clear_active_run",
    "command_for_argv",
    "compute_plan_hash",
    "gate_command",
    "is_in_task_run",
    "load_plan",
    "make_run_started_event",
    "make_step_completed_event",
    "make_step_dispatched_event",
    "read_active_run",
    "read_events",
    "record_dispatch_complete",
    "step_dir_for",
    "task_project_env",
    "task_run_id_env",
    "task_step_id_env",
    "verify_chain",
    "write_active_run",
]
