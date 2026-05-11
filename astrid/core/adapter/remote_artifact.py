"""Remote-artifact adapter — schema-reserved, rejects at runtime in Sprint 3 (lands in Sprint 5a)."""

from __future__ import annotations

from astrid.core.adapter import CompleteResult, DispatchResult, PollResult, RunContext
from astrid.core.task.plan import Step


REMOTE_ARTIFACT_DEFERRAL = (
    "astrid start / astrid next: step {step_id!r} declares adapter 'remote-artifact'; "
    "not yet implemented (Sprint 5a). Use --adapter local or manual."
)


class RemoteArtifactAdapter:
    name = "remote-artifact"

    def dispatch(self, step: Step, run_ctx: RunContext) -> DispatchResult:
        raise NotImplementedError(REMOTE_ARTIFACT_DEFERRAL.format(step_id=step.id))

    def poll(self, step: Step, run_ctx: RunContext) -> PollResult:
        raise NotImplementedError(REMOTE_ARTIFACT_DEFERRAL.format(step_id=step.id))

    def complete(self, step: Step, run_ctx: RunContext) -> CompleteResult:
        raise NotImplementedError(REMOTE_ARTIFACT_DEFERRAL.format(step_id=step.id))
