"""STOP-LINE: tab restart + re-export ASTRID_SESSION_ID restores binding.

A 'tab restart' is simulated by:
1. Run cmd_attach → emits a session file + an export line with a ULID.
2. Capture the SID.
3. Clear ASTRID_SESSION_ID from env (the 'closing the tab' moment).
4. Re-export the SID and call resolve_current_session().
5. Assert the returned Session matches the on-disk record.

If sessions are NOT resumable across this dance, the whole Sprint 1 design
collapses (sessions are explicitly resumable, never auto-expire).
"""

from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path

import pytest

from astrid.core.project import paths as project_paths
from astrid.core.session import cli, paths as session_paths
from astrid.core.session.binding import (
    ASTRID_SESSION_ID_ENV,
    resolve_current_session,
)
from astrid.core.session.identity import Identity, write_identity


def _seed_project(projects_root: Path, slug: str) -> Path:
    pdir = projects_root / slug
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
    return pdir


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv(session_paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "home").mkdir()
    write_identity(Identity(agent_id="claude-1", created_at="2026-05-11T00:00:00Z"))
    return {"home": tmp_path / "home", "projects": tmp_path / "projects"}


def _attach_args(**kw: object) -> argparse.Namespace:
    defaults = {"project": "demo", "timeline": None, "session": None, "as_agent": None}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _parse_sid(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("export ASTRID_SESSION_ID="):
            return line.split("=", 1)[1]
    raise AssertionError(f"export line not in output:\n{output}")


def test_attach_emits_session_file_and_export_line(env: dict[str, Path]) -> None:
    _seed_project(env["projects"], "demo")
    buf = StringIO()
    cli.cmd_attach(_attach_args(), out=buf)
    sid = _parse_sid(buf.getvalue())
    assert (env["home"] / "sessions" / f"{sid}.json").exists()


def test_tab_restart_and_re_export_restores_session(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_project(env["projects"], "demo")
    buf = StringIO()
    cli.cmd_attach(_attach_args(timeline="primary"), out=buf)
    sid = _parse_sid(buf.getvalue())

    # Simulate the tab closing: ASTRID_SESSION_ID falls out of the env.
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    assert resolve_current_session() is None

    # Operator re-exports the same SID in a fresh tab.
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, sid)
    restored = resolve_current_session()
    assert restored is not None
    assert restored.id == sid
    assert restored.project == "demo"
    assert restored.timeline == "primary"


def test_session_file_survives_arbitrary_subsequent_attaches(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attaching a SECOND session in a new tab must NOT delete the first one."""

    _seed_project(env["projects"], "demo")
    buf_a = StringIO()
    cli.cmd_attach(_attach_args(), out=buf_a)
    sid_a = _parse_sid(buf_a.getvalue())

    buf_b = StringIO()
    cli.cmd_attach(_attach_args(), out=buf_b)
    sid_b = _parse_sid(buf_b.getvalue())
    assert sid_b != sid_a

    # Both files still on disk.
    assert (env["home"] / "sessions" / f"{sid_a}.json").exists()
    assert (env["home"] / "sessions" / f"{sid_b}.json").exists()

    # And tab A's binding is restorable.
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, sid_a)
    restored = resolve_current_session()
    assert restored is not None and restored.id == sid_a
