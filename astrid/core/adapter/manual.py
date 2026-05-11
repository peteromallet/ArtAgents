"""Manual-adapter stub — out-of-band ack-driven or inbox-driven completion. Implemented in T12."""

from __future__ import annotations

from astrid.core.adapter import CompleteResult, DispatchResult, PollResult, RunContext
from astrid.core.task.plan import Step


class ManualAdapter:
    name = "manual"

    def dispatch(self, step: Step, run_ctx: RunContext) -> DispatchResult:
        raise NotImplementedError("ManualAdapter.dispatch: implemented in T12")

    def poll(self, step: Step, run_ctx: RunContext) -> PollResult:
        raise NotImplementedError("ManualAdapter.poll: implemented in T12")

    def complete(self, step: Step, run_ctx: RunContext) -> CompleteResult:
        raise NotImplementedError("ManualAdapter.complete: implemented in T12")
