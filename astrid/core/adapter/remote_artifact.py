"""Remote-artifact adapter — schema-reserved in Sprint 3; rejects with the exact deferral string."""

from __future__ import annotations

from astrid.core.adapter import CompleteResult, DispatchResult, PollResult, RunContext
from astrid.core.task.plan import Step


class RemoteArtifactDeferralError(RuntimeError):
    """Raised by the remote-artifact adapter at dispatch time in Sprint 3."""


def _deferral_message(step_id: str) -> str:
    return (
        f"astrid start / astrid next: step '{step_id}' declares adapter 'remote-artifact'; "
        f"not yet implemented (Sprint 5a). Use --adapter local or manual."
    )


# Pre-stored template kept for T22 to assert against without re-typing the literal.
REMOTE_ARTIFACT_DEFERRAL = (
    "astrid start / astrid next: step '{step_id}' declares adapter 'remote-artifact'; "
    "not yet implemented (Sprint 5a). Use --adapter local or manual."
)


class RemoteArtifactAdapter:
    """Stub adapter — every method raises with the deferral string. cmd_next catches and exits non-zero."""

    name = "remote-artifact"

    def dispatch(self, step: Step, run_ctx: RunContext) -> DispatchResult:
        raise RemoteArtifactDeferralError(_deferral_message(step.id))

    def poll(self, step: Step, run_ctx: RunContext) -> PollResult:
        raise RemoteArtifactDeferralError(_deferral_message(step.id))

    def complete(self, step: Step, run_ctx: RunContext) -> CompleteResult:
        raise RemoteArtifactDeferralError(_deferral_message(step.id))
