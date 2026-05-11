"""Tests for cmd_sessions_takeover (orphan path, live path, warm-target guard)."""

from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path

import pytest

from astrid.core.project import paths as project_paths
from astrid.core.project.current_run import write_current_run
from astrid.core.session import cli, paths as session_paths
from astrid.core.session.binding import ASTRID_SESSION_ID_ENV
from astrid.core.session.identity import Identity, write_identity
from astrid.core.session.lease import (
    bump_epoch_and_swap_session,
    read_lease,
    release_writer_lease,
    write_lease_init,
)
from astrid.core.session.model import Session
from astrid.core.task.events import ZERO_HASH, append_event_locked, read_events


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv(session_paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "home").mkdir()
    write_identity(Identity(agent_id="claude-1", created_at="2026-05-11T00:00:00Z"))
    return {"home": tmp_path / "home", "projects": tmp_path / "projects"}


def _seed_project_with_run(
    env_paths: dict[str, Path],
    slug: str = "demo",
    run_id: str = "01RUN",
    *,
    writer_sid: str,
) -> Path:
    pdir = env_paths["projects"] / slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text(
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
    run_dir = pdir / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").touch()
    write_lease_init(run_dir, session_id=writer_sid, plan_hash="")
    write_current_run(slug, run_id)
    return run_dir


def _mint_session(
    home: Path, sid: str, *, project: str = "demo", run_id: str | None = "01RUN"
) -> Session:
    sessions = home / "sessions"
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


def test_takeover_requires_caller_to_be_bound(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    rc = cli.cmd_sessions_takeover(
        argparse.Namespace(target="01RUN", force=False), out=StringIO()
    )
    assert rc == 2


def test_takeover_orphan_path_claims_lease_and_bumps_epoch(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _seed_project_with_run(env, writer_sid="S-OLD")
    release_writer_lease(run_dir)
    caller = _mint_session(env["home"], "S-CLAIM")
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, caller.id)

    buf = StringIO()
    rc = cli.cmd_sessions_takeover(
        argparse.Namespace(target="01RUN", force=False), out=buf
    )
    assert rc == 0
    assert "claimed orphan lease" in buf.getvalue()
    lease = read_lease(run_dir)
    assert lease["attached_session_id"] == caller.id
    assert lease["writer_epoch"] == 1
    events = read_events(run_dir / "events.jsonl")
    assert events[-1]["kind"] == "takeover"
    assert events[-1]["new_session"] == caller.id


def test_takeover_live_path_bumps_epoch_and_swaps(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _seed_project_with_run(env, writer_sid="S-PREV")
    _mint_session(env["home"], "S-PREV")  # session file exists for target lookup
    caller = _mint_session(env["home"], "S-NEW")
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, caller.id)

    rc = cli.cmd_sessions_takeover(
        argparse.Namespace(target="S-PREV", force=False), out=StringIO()
    )
    # The target has no events written → not warm; takeover proceeds.
    assert rc == 0
    lease = read_lease(run_dir)
    assert lease["attached_session_id"] == caller.id
    assert lease["writer_epoch"] == 1
    events = read_events(run_dir / "events.jsonl")
    takeover = events[-1]
    assert takeover["kind"] == "takeover"
    assert takeover["prev_session"] == "S-PREV"
    assert takeover["new_session"] == caller.id


def test_takeover_refuses_warm_target_without_force(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _seed_project_with_run(env, writer_sid="S-PREV")
    # Write a recent event so the target is "warm".
    append_event_locked(
        run_dir,
        {"kind": "step_dispatched", "plan_step_id": "x", "command": "noop"},
        expected_writer_epoch=0,
        expected_prev_hash=ZERO_HASH,
    )
    _mint_session(env["home"], "S-PREV")
    caller = _mint_session(env["home"], "S-NEW")
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, caller.id)

    rc = cli.cmd_sessions_takeover(
        argparse.Namespace(target="S-PREV", force=False), out=StringIO()
    )
    assert rc == 2
    # Lease still names the previous writer.
    assert read_lease(run_dir)["attached_session_id"] == "S-PREV"


def test_takeover_force_overrides_warm_guard(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _seed_project_with_run(env, writer_sid="S-PREV")
    append_event_locked(
        run_dir,
        {"kind": "step_dispatched", "plan_step_id": "x", "command": "noop"},
        expected_writer_epoch=0,
        expected_prev_hash=ZERO_HASH,
    )
    _mint_session(env["home"], "S-PREV")
    caller = _mint_session(env["home"], "S-NEW")
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, caller.id)

    rc = cli.cmd_sessions_takeover(
        argparse.Namespace(target="S-PREV", force=True), out=StringIO()
    )
    assert rc == 0
    assert read_lease(run_dir)["attached_session_id"] == caller.id


def test_takeover_unknown_target_errors(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_project_with_run(env, writer_sid="S-PREV")
    caller = _mint_session(env["home"], "S-NEW")
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, caller.id)
    rc = cli.cmd_sessions_takeover(
        argparse.Namespace(target="NONEXISTENT", force=False), out=StringIO()
    )
    assert rc == 2
