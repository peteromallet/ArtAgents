"""Tests for cmd_status — asserts the literal breadcrumb template."""

from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path

import pytest

from astrid.core.project import paths as project_paths
from astrid.core.project.current_run import write_current_run
from astrid.core.project.project import create_project
from astrid.core.session import cli, paths as session_paths
from astrid.core.session.binding import ASTRID_SESSION_ID_ENV
from astrid.core.session.identity import Identity, write_identity
from astrid.core.session.lease import (
    release_writer_lease,
    write_lease_init,
)
from astrid.core.session.model import Session
from astrid.core.task.events import ZERO_HASH, append_event_locked


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv(session_paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "home").mkdir()
    write_identity(Identity(agent_id="claude-1", created_at="2026-05-11T00:00:00Z"))
    return {"home": tmp_path / "home", "projects": tmp_path / "projects"}


def _mint_session(
    home: Path, sid: str, *, project: str, run_id: str | None, role: str = "writer"
) -> Session:
    sessions = home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sess = Session(
        id=sid,
        project=project,
        timeline="primary",
        run_id=run_id,
        agent_id="claude-1",
        attached_at="2026-05-11T00:00:00Z",
        last_used_at="2026-05-11T00:00:00Z",
        role=role,  # type: ignore[arg-type]
    )
    sess.to_json(sessions / f"{sid}.json")
    return sess


def test_unbound_no_identity_triggers_bootstrap_then_lists_projects(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Status with identity already present + unbound → lists discoverable projects."""

    create_project("alpha")
    create_project("beta")
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    buf = StringIO()
    rc = cli.cmd_status(argparse.Namespace(), out=buf)
    assert rc == 0
    out = buf.getvalue()
    assert cli.STATUS_UNBOUND_HEADER in out
    assert "astrid attach alpha" in out
    assert "astrid attach beta" in out


def test_unbound_status_start_uses_single_concrete_project(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    create_project("demo")
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    buf = StringIO()
    rc = cli.cmd_status(argparse.Namespace(), out=buf)
    assert rc == 0
    out = buf.getvalue()
    assert "start:\n  astrid attach demo" in out
    assert "after attach:" in out
    assert "astrid skills list" in out
    assert "astrid orchestrators list" in out
    assert "astrid executors list" in out
    assert "astrid elements list" in out


def test_unbound_no_projects_under_root_prints_no_projects(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    buf = StringIO()
    cli.cmd_status(argparse.Namespace(), out=buf)
    out = buf.getvalue()
    assert cli.NO_PROJECTS_FOUND in out
    assert "astrid projects create <slug>" in out


def test_unbound_status_warns_when_default_project_is_not_discoverable(
    env: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from astrid.core.session import config

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    config.set_default_project("missing")
    create_project("demo")
    buf = StringIO()
    cli.cmd_status(argparse.Namespace(), out=buf)
    out = buf.getvalue()
    assert "configured default project: missing (not found under current projects root)" in out
    assert "astrid attach              # attach default project" not in out
    assert "astrid attach demo" in out


def test_bound_writer_breadcrumb_template(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    pdir = create_project("demo")["slug"]  # → "demo"
    project_dir = env["projects"] / pdir
    run_dir = project_dir / "runs" / "01RUN"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").touch()
    sess = _mint_session(env["home"], "S-1", project="demo", run_id="01RUN")
    write_lease_init(run_dir, session_id=sess.id, plan_hash="")
    write_current_run("demo", "01RUN")
    # Add one event so the breadcrumb has data to show.
    append_event_locked(
        run_dir,
        {"kind": "step_dispatched", "plan_step_id": "step-1", "command": "noop"},
        expected_writer_epoch=0,
        expected_prev_hash=ZERO_HASH,
    )
    # Add an inbox entry so the count is non-zero.
    inbox = run_dir / "inbox"
    inbox.mkdir()
    (inbox / "ping.json").write_text('{"hello": "world"}', encoding="utf-8")

    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, sess.id)
    buf = StringIO()
    rc = cli.cmd_status(argparse.Namespace(), out=buf)
    assert rc == 0
    out = buf.getvalue()
    assert f"session: {sess.id}" in out
    assert "agent: claude-1" in out
    assert "project: demo" in out
    assert "timeline: primary" in out
    assert "run: 01RUN" in out
    assert "current step: step-1" in out
    assert "recent events (last 5):" in out
    assert "step_dispatched" in out
    assert "inbox: 1" in out
    assert "role: writer" in out
    assert "task:" in out
    assert "astrid next --project demo" in out
    assert "discover:" in out
    assert "astrid skills list" in out
    assert "astrid orchestrators list" in out
    assert "astrid executors list" in out
    assert "astrid elements list" in out
    # No takeover hint for the writer.
    assert "astrid sessions takeover" not in out


def test_bound_status_without_run_includes_start_hint(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    create_project("demo")
    sess = _mint_session(env["home"], "S-NO-RUN", project="demo", run_id=None)
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, sess.id)
    buf = StringIO()
    rc = cli.cmd_status(argparse.Namespace(), out=buf)
    assert rc == 0
    out = buf.getvalue()
    assert "run: (none)" in out
    assert "task:" in out
    assert "astrid start <orchestrator-id> --project demo" in out


def test_bound_reader_breadcrumb_includes_takeover_hint(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    create_project("demo")
    run_dir = env["projects"] / "demo" / "runs" / "01RUN"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").touch()
    write_lease_init(run_dir, session_id="S-WRITER", plan_hash="")
    write_current_run("demo", "01RUN")
    reader = _mint_session(env["home"], "S-READER", project="demo", run_id="01RUN", role="reader")
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, reader.id)
    buf = StringIO()
    cli.cmd_status(argparse.Namespace(), out=buf)
    out = buf.getvalue()
    assert "role: reader" in out
    assert "astrid sessions takeover 01RUN" in out
    assert "S-WRITER" in out


def test_bound_orphan_pending_breadcrumb_includes_claim_hint(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    create_project("demo")
    run_dir = env["projects"] / "demo" / "runs" / "01RUN"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").touch()
    write_lease_init(run_dir, session_id="S-OLD", plan_hash="")
    release_writer_lease(run_dir)
    write_current_run("demo", "01RUN")
    caller = _mint_session(env["home"], "S-CALL", project="demo", run_id="01RUN")
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, caller.id)
    buf = StringIO()
    cli.cmd_status(argparse.Namespace(), out=buf)
    out = buf.getvalue()
    assert "role: orphan-pending" in out
    assert "astrid sessions takeover 01RUN" in out
