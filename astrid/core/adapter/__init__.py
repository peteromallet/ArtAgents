"""Adapter Protocol for location-agnostic step execution (local, manual, remote-artifact).

Adapters dispatch, poll, and complete a Step. They MUST NOT call
``events.append_event_locked`` directly — event emission is owned by ``cmd_next``
and ``gate.record_dispatch_complete`` (single emission point per Sprint 3 brief).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from astrid.core.task.plan import CostEntry, Step


DispatchStatus = Literal["dispatched", "rejected"]
PollStatus = Literal["pending", "running", "done", "failed"]
CompleteStatus = Literal["completed", "failed", "awaiting_fetch"]


@dataclass(frozen=True)
class RunContext:
    """Subset of run state an adapter needs. Populated by cmd_next at dispatch time."""

    slug: str
    run_id: str
    project_root: Path
    plan_step_path: tuple[str, ...]
    step_version: int
    iteration: int | None = None
    item_id: str | None = None


@dataclass(frozen=True)
class DispatchResult:
    status: DispatchStatus
    pid: int | None = None
    started_at: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PollResult:
    status: PollStatus
    returncode: int | None = None


@dataclass(frozen=True)
class CompleteResult:
    status: CompleteStatus
    returncode: int | None = None
    cost: CostEntry | None = None
    reason: str | None = None


class Adapter(Protocol):
    """Protocol every concrete adapter implements.

    Forbidden: adapters MUST NOT import or call append_event_locked. Event
    emission is owned by cmd_next + gate.record_dispatch_complete.
    """

    name: str

    def dispatch(self, step: Step, run_ctx: RunContext) -> DispatchResult: ...

    def poll(self, step: Step, run_ctx: RunContext) -> PollResult: ...

    def complete(self, step: Step, run_ctx: RunContext) -> CompleteResult: ...


__all__ = [
    "Adapter",
    "RunContext",
    "DispatchResult",
    "PollResult",
    "CompleteResult",
    "DispatchStatus",
    "PollStatus",
    "CompleteStatus",
]
