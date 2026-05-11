"""Local-adapter stub — subprocess-based execution. Implemented in T11."""

from __future__ import annotations

from astrid.core.adapter import CompleteResult, DispatchResult, PollResult, RunContext
from astrid.core.task.plan import Step


class LocalAdapter:
    name = "local"

    def dispatch(self, step: Step, run_ctx: RunContext) -> DispatchResult:
        raise NotImplementedError("LocalAdapter.dispatch: implemented in T11")

    def poll(self, step: Step, run_ctx: RunContext) -> PollResult:
        raise NotImplementedError("LocalAdapter.poll: implemented in T11")

    def complete(self, step: Step, run_ctx: RunContext) -> CompleteResult:
        raise NotImplementedError("LocalAdapter.complete: implemented in T11")
