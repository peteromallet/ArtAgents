"""Tests for cmd_attach + cmd_sessions_detach + cmd_sessions_ls."""

from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path

import pytest

from astrid.core.project import paths as project_paths
from astrid.core.project.current_run import write_current_run
from astrid.core.session import cli, paths as session_paths
from astrid.core.session.identity import Identity, write_identity
from astrid.core.session.lease import release_writer_lease, write_lease_init


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv(session_paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "home").mkdir()
    write_identity(Identity(agent_id="claude-1", created_at="2026-05-11T00:00:00Z"))
    return {"home": tmp_path / "home", "projects": tmp_path / "projects"}


def _seed_project(projects_root: Path, slug: str) -> Path:
    pdir = projects_root / slug
    pdir.mkdir(parents=True, exist_ok=True)

    # Seed a default timeline so Sprint 2 resolution works.
    from astrid.core.session.ulid import generate_ulid

    timeline_ulid = generate_ulid()
    tdir = pdir / "timelines" / timeline_ulid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "assembly.json").write_text(
        json.dumps({"schema_version": 1, "assembly": {}}), encoding="utf-8"
    )
    (tdir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contributing_runs": [],
                "final_outputs": [],
                "tombstoned_at": None,
            }
        ),
        encoding="utf-8",
    )
    (tdir / "display.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "slug": "primary",
                "name": "Primary",
                "is_default": True,
            }
        ),
        encoding="utf-8",
    )
    (pdir / "project.json").write_text(
        json.dumps(
            {
                "created_at": "2026-05-11T00:00:00Z",
                "name": slug,
                "schema_version": 1,
                "slug": slug,
                "updated_at": "2026-05-11T00:00:00Z",
                "default_timeline_id": timeline_ulid,
            }
        ),
        encoding="utf-8",
    )
    return pdir


def _args(**kw: object) -> argparse.Namespace:
    defaults = {
        "project": "demo",
        "timeline": None,
        "session": None,
        "as_agent": None,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ----- cmd_attach -------------------------------------------------------


def test_attach_no_current_run_role_is_writer(env: dict[str, Path]) -> None:
    _seed_project(env["projects"], "demo")
    buf = StringIO()
    rc = cli.cmd_attach(_args(), out=buf)
    assert rc == 0
    output = buf.getvalue()
    assert cli.ATTACH_HEADER in output
    assert "export ASTRID_SESSION_ID=" in output
    assert "role: writer" in output
    assert "run: (none)" in output
    # A session file was written.
    sessions = list((env["home"] / "sessions").iterdir())
    assert len(sessions) == 1


def test_attach_to_held_run_yields_reader_role_with_takeover_hint(
    env: dict[str, Path],
) -> None:
    pdir = _seed_project(env["projects"], "demo")
    run_dir = pdir / "runs" / "01RUN"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").touch()
    write_lease_init(run_dir, session_id="S-WRITER", plan_hash="")
    write_current_run("demo", "01RUN")
    buf = StringIO()
    rc = cli.cmd_attach(_args(), out=buf)
    assert rc == 0
    output = buf.getvalue()
    assert "role: reader" in output
    assert "astrid sessions takeover 01RUN" in output
    assert "S-WRITER" in output


def test_attach_to_orphan_lease_yields_orphan_pending_role(
    env: dict[str, Path],
) -> None:
    pdir = _seed_project(env["projects"], "demo")
    run_dir = pdir / "runs" / "01RUN"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").touch()
    write_lease_init(run_dir, session_id="S-OLD", plan_hash="")
    release_writer_lease(run_dir)
    write_current_run("demo", "01RUN")
    buf = StringIO()
    rc = cli.cmd_attach(_args(), out=buf)
    assert rc == 0
    output = buf.getvalue()
    assert "role: orphan-pending" in output
    assert "astrid sessions takeover 01RUN" in output


def test_attach_with_session_resumes_existing(env: dict[str, Path]) -> None:
    _seed_project(env["projects"], "demo")
    # Create an initial session.
    buf = StringIO()
    cli.cmd_attach(_args(), out=buf)
    first_sid = next(iter((env["home"] / "sessions").iterdir())).stem

    # Re-attach with --session.
    buf2 = StringIO()
    rc = cli.cmd_attach(_args(session=first_sid), out=buf2)
    assert rc == 0
    assert f"export ASTRID_SESSION_ID={first_sid}" in buf2.getvalue()
    # Still exactly one session file.
    assert len(list((env["home"] / "sessions").iterdir())) == 1


def test_attach_resume_missing_id_errors(env: dict[str, Path]) -> None:
    _seed_project(env["projects"], "demo")
    buf = StringIO()
    rc = cli.cmd_attach(_args(session="NONEXISTENT"), out=buf)
    assert rc == 2


def test_attach_as_agent_overrides_identity(env: dict[str, Path]) -> None:
    _seed_project(env["projects"], "demo")
    buf = StringIO()
    rc = cli.cmd_attach(_args(as_agent="agent:codex-1"), out=buf)
    assert rc == 0
    sess_file = next(iter((env["home"] / "sessions").iterdir()))
    payload = json.loads(sess_file.read_text())
    assert payload["agent_id"] == "codex-1"


def test_attach_as_agent_rejects_malformed(env: dict[str, Path]) -> None:
    _seed_project(env["projects"], "demo")
    buf = StringIO()
    rc = cli.cmd_attach(_args(as_agent="codex-1"), out=buf)  # missing "agent:" prefix
    assert rc == 2


# ----- cmd_sessions_ls --------------------------------------------------


def test_sessions_ls_empty(env: dict[str, Path]) -> None:
    buf = StringIO()
    rc = cli.cmd_sessions_ls(argparse.Namespace(), out=buf)
    assert rc == 0
    assert "no sessions" in buf.getvalue()


def test_sessions_ls_lists_all(env: dict[str, Path]) -> None:
    _seed_project(env["projects"], "demo")
    _seed_project(env["projects"], "other")
    cli.cmd_attach(_args(project="demo"), out=StringIO())
    cli.cmd_attach(_args(project="other"), out=StringIO())
    buf = StringIO()
    cli.cmd_sessions_ls(argparse.Namespace(), out=buf)
    lines = [ln for ln in buf.getvalue().splitlines() if ln]
    assert len(lines) == 2
    assert any("project=demo" in ln for ln in lines)
    assert any("project=other" in ln for ln in lines)


# ----- cmd_sessions_detach ----------------------------------------------


def test_detach_by_id_removes_session_file(env: dict[str, Path]) -> None:
    _seed_project(env["projects"], "demo")
    cli.cmd_attach(_args(), out=StringIO())
    sid = next(iter((env["home"] / "sessions").iterdir())).stem
    rc = cli.cmd_sessions_detach(argparse.Namespace(session_id=sid), out=StringIO())
    assert rc == 0
    assert not (env["home"] / "sessions" / f"{sid}.json").exists()


def test_detach_without_id_uses_env(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_project(env["projects"], "demo")
    cli.cmd_attach(_args(), out=StringIO())
    sid = next(iter((env["home"] / "sessions").iterdir())).stem
    monkeypatch.setenv("ASTRID_SESSION_ID", sid)
    rc = cli.cmd_sessions_detach(argparse.Namespace(session_id=None), out=StringIO())
    assert rc == 0
    assert not (env["home"] / "sessions" / f"{sid}.json").exists()


def test_detach_without_id_or_env_errors(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ASTRID_SESSION_ID", raising=False)
    rc = cli.cmd_sessions_detach(argparse.Namespace(session_id=None), out=StringIO())
    assert rc == 2


def test_detach_missing_session_errors(env: dict[str, Path]) -> None:
    rc = cli.cmd_sessions_detach(
        argparse.Namespace(session_id="NONEXISTENT"), out=StringIO()
    )
    assert rc == 2
