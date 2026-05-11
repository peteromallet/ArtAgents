"""Thread state primitives for Astrid creative runs.

DEPRECATED (Sprint 1): the user-facing ``astrid thread`` CLI verb was retired
in T8/T12. This package is retained as an INTERNAL library (DEC-001) because
orchestrator/executor runners and pack ``run.py`` files still depend on
``ThreadIndexStore`` and the variant-sidecar protocol.

# TODO(sprint-N): retire astrid/threads/ entirely; depends on orchestrator/executor
# runner rewrite and pack run.py migration off ThreadIndexStore + variant sidecars.
# See plan_v4 Phase 5.
"""

from __future__ import annotations

from .ids import generate_group_id, generate_run_id, generate_thread_id, is_ulid
from .index import ThreadIndexError, ThreadIndexLockTimeout, ThreadIndexStore
from .record import build_run_record, finalize_run_record
from .schema import SCHEMA_VERSION
from .wrapper import begin_executor_run, begin_orchestrator_run, finalize_exception, finalize_result, subprocess_env

__all__ = [
    "SCHEMA_VERSION",
    "ThreadIndexError",
    "ThreadIndexLockTimeout",
    "ThreadIndexStore",
    "begin_executor_run",
    "begin_orchestrator_run",
    "build_run_record",
    "finalize_exception",
    "finalize_result",
    "finalize_run_record",
    "generate_group_id",
    "generate_run_id",
    "generate_thread_id",
    "is_ulid",
    "subprocess_env",
]
