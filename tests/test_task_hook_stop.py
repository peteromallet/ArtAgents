"""cmd_hook_stop discovery contract (Sprint 1 / DEC-016).

Sprint 1 retires the projects-root scan tier and the legacy
``active_run.json`` pointer. Discovery is now:

  (A) session-bound resolution via ``ASTRID_SESSION_ID`` — takes precedence.
  (B) cwd-ancestor walk for ``current_run.json`` — fallback.

Tests:
- Empty/silent no-op when nothing matches.
- session-bound resolution wins when ``ASTRID_SESSION_ID`` is set.
- cwd-walk discovers via ``current_run.json``.
- Unrelated cwd with no session => silent no-op (projects-root scan dropped).
"""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _lifecycle_fixtures import setup_run  # noqa: E402

from astrid.core.session.identity import Identity, write_identity
from astrid.core.session.model import Session
from astrid.core.session.paths import session_path, sessions_dir
from astrid.core.session.ulid import generate_ulid
from astrid.core.task.hook import cmd_hook_stop
from astrid.core.task.lifecycle import cmd_next


_BODY_CODE = '''from astrid.orchestrate import orchestrator, code
@orchestrator("demo.code")
def main(): return [code("step_a", argv=["echo", "alpha"])]
'''


@pytest.fixture(autouse=True)
def _isolate_session_env(monkeypatch, tmp_path):
    # The autouse conftest fixture sets ASTRID_SESSION_ID for the whole run;
    # hook tests need to control it explicitly per-case.
    astrid_home = tmp_path / "_astrid_home_hook"
    astrid_home.mkdir(exist_ok=True)
    monkeypatch.setenv("ASTRID_HOME", str(astrid_home))
    monkeypatch.delenv("ASTRID_SESSION_ID", raising=False)
    yield


def _capture_cmd_next(slug: str, projects_root: Path) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        rc = cmd_next(["--project", slug], projects_root=projects_root)
    assert rc == 0
    return buf.getvalue()


def _capture_hook(*, cwd: Path, projects_root: Path) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_hook_stop([], cwd=cwd, projects_root=projects_root)
    return rc, out.getvalue(), err.getvalue()


def test_empty_projects_root_is_silent_noop(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    cwd = tmp_path / "cwd"
    projects.mkdir()
    cwd.mkdir()
    rc, out, err = _capture_hook(cwd=cwd, projects_root=projects)
    assert rc == 0
    assert out == ""
    assert err == ""


def test_unrelated_cwd_no_session_is_silent_noop(tmp_path: Path) -> None:
    # DEC-016: the projects-root scan tier is removed. A real run exists for
    # 'p' but the hook is invoked from a sibling cwd with no session bound,
    # so discovery must fall through to silent no-op rather than scanning
    # the projects root.
    _, projects = setup_run(
        tmp_path, "demo", "code", _BODY_CODE, "demo.code", run_id="r1", project="p"
    )
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    rc, out, err = _capture_hook(cwd=unrelated, projects_root=projects)
    assert rc == 0
    assert out == ""
    assert err == ""


def test_discovers_via_cwd_ancestor_walk(tmp_path: Path) -> None:
    _, projects = setup_run(
        tmp_path, "demo", "code", _BODY_CODE, "demo.code", run_id="r2", project="p"
    )
    expected = _capture_cmd_next("p", projects)

    rc, out, err = _capture_hook(cwd=projects / "p", projects_root=projects)

    assert rc == 0
    assert err == ""
    assert out == expected


def test_session_bound_resolution_wins(tmp_path: Path, monkeypatch) -> None:
    _, projects = setup_run(
        tmp_path, "demo", "code", _BODY_CODE, "demo.code", run_id="r3", project="p"
    )
    expected = _capture_cmd_next("p", projects)

    write_identity(Identity(agent_id="hook-test", created_at="2026-01-01T00:00:00Z"))
    sessions_dir().mkdir(parents=True, exist_ok=True)
    session = Session(
        id=generate_ulid(),
        project="p",
        timeline=None,
        run_id="r3",
        agent_id="hook-test",
        attached_at="2026-01-01T00:00:00Z",
        last_used_at="2026-01-01T00:00:00Z",
        role="writer",
    )
    session.to_json(session_path(session.id))
    monkeypatch.setenv("ASTRID_SESSION_ID", session.id)

    # cwd is unrelated; session-bound discovery should still find slug 'p'.
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    rc, out, err = _capture_hook(cwd=unrelated, projects_root=projects)
    assert rc == 0
    assert err == ""
    assert out == expected


def test_silent_noop_when_cwd_has_no_run_and_no_session(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    (cwd / "some_other_file.txt").write_text("noise", encoding="utf-8")

    rc, out, err = _capture_hook(cwd=cwd, projects_root=projects)
    assert rc == 0
    assert out == ""
    assert err == ""
