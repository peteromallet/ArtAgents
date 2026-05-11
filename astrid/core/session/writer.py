"""WriterContext: the session-scoped gate around every mutating verb.

On entry, WriterContext:

1. Reads ``<project>/current_run.json``. If the on-disk ``run_id`` does not
   match ``session.run_id``, the session is auto-rebound to the on-disk
   run id via :func:`dataclasses.replace`, **and the on-disk session file
   is rewritten** to match. This is a deliberate side effect: tests that
   snapshot the session file before invoking a verb must re-read after via
   the ``attached_session`` fixture's ``refresh()`` helper.
2. If ``session.run_id`` is still ``None`` after the rebind step (no run
   has been started yet), raises :class:`NoRunBoundError` — a
   session-state condition, defined LOCALLY in this module (NOT in
   ``events.py``; the event log is fine, the session is just not pointing
   at a run).
3. Reads ``runs/<run_id>/lease.json`` and performs the WRITER-AUTH CHECK:
   if ``lease['attached_session_id'] != session.id`` → :class:`NotWriterError`.
4. Captures ``expected_writer_epoch`` and ``plan_hash`` from the lease for
   use by :meth:`append`.

Inside the ``with`` block, :meth:`append` is the only sanctioned way to
write to ``events.jsonl``: it routes through
:func:`append_event_locked` with the captured epoch and a freshly-read tail
(both under flock). A stale writer that lost a takeover between
``__enter__`` and ``append`` is rejected at append time by the stale-epoch
CAS.

:func:`writer_context_from_decision` is the factory used by post-dispatch
``record_*`` helpers in ``gate.py``: it accepts a ``GateDecision``-shaped
object (any object exposing ``.session``) and produces a fresh
WriterContext that performs the same writer-auth check on entry.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from astrid.core.project.current_run import read_current_run
from astrid.core.project.paths import project_dir
from astrid.core.session.lease import read_lease
from astrid.core.session.model import Session, now_iso
from astrid.core.session.paths import session_path
from astrid.core.task.events import (
    NotWriterError,
    append_event_locked,
)


class NoRunBoundError(Exception):
    """The active session has no ``run_id`` to write against.

    Session-state condition. Distinct from the event-log CAS errors
    (StaleTailError / StaleEpochError / NotWriterError) which live in
    :mod:`astrid.core.task.events`. Callers typically respond by either
    prompting the user to ``astrid start`` a run or surfacing the error.
    """

    def __init__(self, session_id: str, project: str) -> None:
        self.session_id = session_id
        self.project = project
        super().__init__(
            f"session {session_id!r} is bound to project {project!r} but has no run_id; "
            "start a run before mutating verbs"
        )


class _HasSession(Protocol):
    """Structural type for the ``GateDecision`` factory contract.

    T8/T9 extend ``GateDecision`` with ``run_dir`` / ``writer_epoch_at_dispatch``
    / ``session_id`` fields; T6 only needs ``.session`` and re-derives the
    rest from disk so the factory works regardless of how those fields are
    populated.
    """

    session: Session


class WriterContext:
    """Auto-rebinding writer-auth gate around the locked event-append helper."""

    def __init__(self, session: Session, *, root: str | Path | None = None) -> None:
        self.session: Session = session
        self._root = root
        self.run_dir: Path | None = None
        self.expected_writer_epoch: int = -1
        self.plan_hash: str = ""

    def __enter__(self) -> "WriterContext":
        # (1) Auto-rebind to the on-disk current_run.json if it has moved
        # since the session was minted. This SILENTLY rewrites the session
        # file when run_id changes; tests that snapshot the file pre-verb
        # must refresh() after.
        on_disk_run_id = read_current_run(self.session.project, root=self._root)
        if on_disk_run_id != self.session.run_id:
            self.session = replace(
                self.session, run_id=on_disk_run_id, last_used_at=now_iso()
            )
            self.session.to_json(session_path(self.session.id))

        # (2) Refuse to mutate without a bound run.
        if self.session.run_id is None:
            raise NoRunBoundError(self.session.id, self.session.project)

        # (3) Compute run_dir.
        self.run_dir = (
            project_dir(self.session.project, root=self._root)
            / "runs"
            / self.session.run_id
        )

        # (4) Read lease + (5) writer-auth + (6) capture epoch/plan_hash.
        lease = read_lease(self.run_dir)
        attached = lease.get("attached_session_id")
        if attached != self.session.id:
            raise NotWriterError(session_id=self.session.id, writer_id=attached)
        self.expected_writer_epoch = lease["writer_epoch"]
        self.plan_hash = lease["plan_hash"]
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # No state to release — the locked-append helper owns its own flock
        # for each call; this context just gates entry and carries captured
        # epoch into append() invocations.
        return None

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        """Append ``event`` via :func:`append_event_locked`.

        Reads the tail freshly inside the locked-append call (under flock)
        and CAS-checks both tail and epoch atomically. A takeover between
        ``__enter__`` and this call surfaces as :class:`StaleEpochError`
        from :func:`append_event_locked`.
        """

        if self.run_dir is None:
            raise RuntimeError("WriterContext.append called outside of `with` block")
        # The tail CAS in append_event_locked re-reads under the flock; we
        # supply the current tail by reading it (unlocked) immediately
        # prior. If a concurrent appender slipped in, the under-lock tail
        # will differ and StaleTailError fires — exactly the apex contract.
        from astrid.core.task.events import _peek_tail_hash  # local import

        expected_prev = _peek_tail_hash(self.run_dir / "events.jsonl")
        return append_event_locked(
            self.run_dir,
            event,
            expected_writer_epoch=self.expected_writer_epoch,
            expected_prev_hash=expected_prev,
        )


def writer_context_from_decision(
    decision: _HasSession,
    *,
    root: str | Path | None = None,
) -> WriterContext:
    """Factory used by post-dispatch ``record_*`` helpers.

    Accepts any object exposing ``.session: Session`` — including the
    extended ``GateDecision`` T8/T9 introduce. Performs the same
    writer-auth check on ``__enter__`` as :class:`WriterContext`.
    """

    return WriterContext(decision.session, root=root)
