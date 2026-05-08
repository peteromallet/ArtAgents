"""Astrid worker package.

The banodoco worker pool implementation lives in ``banodoco_worker``. It polls
the orchestrator's ``claim-next-task`` endpoint, validates SD-034 envelopes,
JWKS-verifies the user JWT, performs an explicit service-role project-ownership
check (FLAG-013), dispatches by ``intent`` to AA's executor registry, then
writes back via ``SupabaseDataProvider.save_timeline`` and reports status via
``update-task-status``.
"""

from .banodoco_worker import (
    BanodocoWorker,
    DispatchError,
    IntentDispatcher,
    ProjectOwnershipError,
    WorkerConfig,
    run_worker,
)

__all__ = [
    "BanodocoWorker",
    "DispatchError",
    "IntentDispatcher",
    "ProjectOwnershipError",
    "WorkerConfig",
    "run_worker",
]
