"""Tests for WriterContext: auto-rebind + writer-auth + locked-append plumbing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.project import paths as project_paths
from astrid.core.project.current_run import write_current_run
from astrid.core.session import paths as session_paths
from astrid.core.session.lease import (
    bump_epoch_and_swap_session,
    read_lease,
    release_writer_lease,
    write_lease_init,
)
from astrid.core.session.model import Session
from astrid.core.session.writer import (
    NoRunBoundError,
    WriterContext,
    writer_context_from_decision,
)
from astrid.core.task.events import (
    NotWriterError,
    StaleEpochError,
    StaleTailError,
    read_events,
    verify_chain,
)


def _mint_session(
    astrid_home: Path,
    *,
    sid: str,
    project: str,
    run_id: str | None = "01HXYZRUN",
) -> Session:
    sessions = astrid_home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sess = Session(
        id=sid,
        project=project,
        timeline=None,
        run_id=run_id,
        agent_id="claude-1",
        attached_at="2026-05-11T00:00:00Z",
        last_used_at="2026-05-11T00:00:00Z",
        role="writer",
    )
    sess.to_json(sessions / f"{sid}.json")
    return sess


def _setup_project(
    projects_root: Path,
    slug: str,
    run_id: str,
    *,
    writer_session_id: str,
) -> Path:
    project = projects_root / slug
    project.mkdir(parents=True, exist_ok=True)
    (project / "project.json").write_text(
        json.dumps(
            {
                "created_at": "2026-05-11T00:00:00Z",
                "name": slug,
                "schema_version": 1,
                "slug": slug,
                "updated_at": "2026-05-11T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    run_dir = project / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "events.jsonl").touch()
    write_lease_init(run_dir, session_id=writer_session_id, plan_hash="")
    write_current_run(slug, run_id)
    return run_dir


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv(session_paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    return {"home": tmp_path / "home", "projects": tmp_path / "projects"}


# ----- happy path --------------------------------------------------------


def test_writer_context_happy_path_appends(env: dict[str, Path]) -> None:
    sess = _mint_session(env["home"], sid="S-1", project="demo", run_id="01RUN")
    run_dir = _setup_project(env["projects"], "demo", "01RUN", writer_session_id=sess.id)
    with WriterContext(sess) as ctx:
        assert ctx.run_dir == run_dir
        assert ctx.expected_writer_epoch == 0
        ev = ctx.append({"kind": "test", "n": 1})
        assert "hash" in ev
    ok, _, err = verify_chain(run_dir / "events.jsonl")
    assert ok and err is None
    events = read_events(run_dir / "events.jsonl")
    assert len(events) == 1
    assert events[0]["kind"] == "test"


# ----- writer-auth -------------------------------------------------------


def test_writer_context_refuses_reader_session(env: dict[str, Path]) -> None:
    """Reader session (lease names a different session) is rejected at __enter__."""

    writer_sess = _mint_session(env["home"], sid="S-WRITER", project="demo", run_id="01RUN")
    run_dir = _setup_project(
        env["projects"], "demo", "01RUN", writer_session_id=writer_sess.id
    )
    pre_bytes = (run_dir / "events.jsonl").read_bytes()
    reader_sess = _mint_session(env["home"], sid="S-READER", project="demo", run_id="01RUN")
    with pytest.raises(NotWriterError) as exc_info:
        with WriterContext(reader_sess):
            pass
    assert exc_info.value.session_id == "S-READER"
    assert exc_info.value.writer_id == "S-WRITER"
    # events.jsonl unchanged.
    assert (run_dir / "events.jsonl").read_bytes() == pre_bytes


def test_orphan_pending_session_refused_then_takeover_promotes(
    env: dict[str, Path],
) -> None:
    """attached_session_id=None → NotWriterError; takeover promotes the claimant."""

    sess = _mint_session(env["home"], sid="S-CLAIM", project="demo", run_id="01RUN")
    run_dir = _setup_project(env["projects"], "demo", "01RUN", writer_session_id="S-OLD")
    release_writer_lease(run_dir)
    assert read_lease(run_dir)["attached_session_id"] is None
    with pytest.raises(NotWriterError) as exc_info:
        with WriterContext(sess):
            pass
    assert exc_info.value.writer_id is None
    # Promote via takeover (claim_orphan_lease is the verb path; either works
    # here — bump+swap also sets attached_session_id):
    from astrid.core.session.lease import claim_orphan_lease

    claim_orphan_lease(run_dir, new_session_id=sess.id)
    with WriterContext(sess) as ctx:
        ev = ctx.append({"kind": "after-claim", "n": 1})
        assert "hash" in ev


# ----- stale-tail / stale-epoch surfacing -------------------------------


def test_stale_epoch_surfaces_when_takeover_intervenes(env: dict[str, Path]) -> None:
    """A takeover after __enter__ but before append → StaleEpochError on append."""

    a = _mint_session(env["home"], sid="S-A", project="demo", run_id="01RUN")
    run_dir = _setup_project(env["projects"], "demo", "01RUN", writer_session_id=a.id)
    with WriterContext(a) as ctx:
        # Simulate a competing tab winning takeover.
        bump_epoch_and_swap_session(
            run_dir, new_session_id="S-B", prev_session_id=a.id, reason="test"
        )
        # The takeover event itself succeeded under its own flock; A's
        # captured epoch (0) no longer matches lease (now 1).
        with pytest.raises(StaleEpochError) as exc_info:
            ctx.append({"kind": "should-reject"})
        assert exc_info.value.expected == 0
        assert exc_info.value.actual == 1


def test_stale_tail_surfaces_when_external_appender_wins_race(
    env: dict[str, Path],
) -> None:
    """If the tail moved between _peek and append (rare under single-thread),
    StaleTailError surfaces. We simulate by reaching past the context to
    write directly under the same lease."""

    sess = _mint_session(env["home"], sid="S-A", project="demo", run_id="01RUN")
    run_dir = _setup_project(env["projects"], "demo", "01RUN", writer_session_id=sess.id)
    from astrid.core.task.events import ZERO_HASH, append_event_locked

    with WriterContext(sess) as ctx:
        # External (still-valid-writer) append races in and moves the tail.
        first = append_event_locked(
            run_dir,
            {"kind": "external", "n": 1},
            expected_writer_epoch=0,
            expected_prev_hash=ZERO_HASH,
        )
        # ctx.append's _peek_tail_hash now sees `first['hash']` (not ZERO),
        # so the next call chains forward cleanly. Force the race shape
        # explicitly by hand-passing a stale prev_hash:
        with pytest.raises(StaleTailError):
            append_event_locked(
                run_dir,
                {"kind": "stale-test", "n": 2},
                expected_writer_epoch=ctx.expected_writer_epoch,
                expected_prev_hash=ZERO_HASH,  # stale on purpose
            )
        # And the recovered path (peek then append) succeeds:
        ev = ctx.append({"kind": "recovered", "n": 3})
        assert ev["hash"] != first["hash"]


# ----- auto-rebind -------------------------------------------------------


def test_auto_rebind_picks_up_new_run_id_and_rewrites_session_file(
    env: dict[str, Path],
) -> None:
    """Session minted before a run was started → __enter__ rebinds to current_run.json
    and silently rewrites the session file on disk."""

    sess = _mint_session(env["home"], sid="S-REBIND", project="demo", run_id=None)
    # A different tab started the run while this session sat detached.
    run_dir = _setup_project(env["projects"], "demo", "01NEWRUN", writer_session_id=sess.id)
    with WriterContext(sess) as ctx:
        # Auto-rebind populated session.run_id from current_run.json.
        assert ctx.session.run_id == "01NEWRUN"
        assert ctx.run_dir == run_dir
        ctx.append({"kind": "rebound", "n": 1})
    # The on-disk session file was rewritten as a side effect.
    on_disk = json.loads((env["home"] / "sessions" / "S-REBIND.json").read_text())
    assert on_disk["run_id"] == "01NEWRUN"
    assert on_disk["last_used_at"] != "2026-05-11T00:00:00Z"  # bumped


def test_no_run_bound_raises_when_current_run_absent(env: dict[str, Path]) -> None:
    sess = _mint_session(env["home"], sid="S-NORUN", project="demo", run_id=None)
    # Project exists but no current_run.json / no runs/ subdir.
    (env["projects"] / "demo").mkdir(parents=True)
    (env["projects"] / "demo" / "project.json").write_text("{}", encoding="utf-8")
    with pytest.raises(NoRunBoundError) as exc_info:
        with WriterContext(sess):
            pass
    assert exc_info.value.session_id == "S-NORUN"
    assert exc_info.value.project == "demo"


# ----- factory ------------------------------------------------------------


def test_writer_context_from_decision_performs_auth_check(env: dict[str, Path]) -> None:
    """The factory accepts any object exposing `.session` and gates on entry."""

    class FakeDecision:
        def __init__(self, sess: Session) -> None:
            self.session = sess

    writer = _mint_session(env["home"], sid="S-W", project="demo", run_id="01RUN")
    _setup_project(env["projects"], "demo", "01RUN", writer_session_id=writer.id)
    with writer_context_from_decision(FakeDecision(writer)) as ctx:
        ctx.append({"kind": "via-factory", "n": 1})

    # A reader session via the same factory is refused.
    reader = _mint_session(env["home"], sid="S-R", project="demo", run_id="01RUN")
    with pytest.raises(NotWriterError):
        with writer_context_from_decision(FakeDecision(reader)):
            pass


def test_no_run_bound_error_is_local_to_writer_module() -> None:
    """NoRunBoundError lives in writer.py, NOT in events.py (DEC: session-state error)."""

    from astrid.core.session.writer import NoRunBoundError as LocalNRBE
    from astrid.core.task import events as ev_mod

    assert LocalNRBE is NoRunBoundError
    assert not hasattr(ev_mod, "NoRunBoundError")
