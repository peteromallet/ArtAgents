"""Sprint 1 CLI gate tests: the unbound allowlist and 'no session bound' error."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

import pytest

from astrid import pipeline
from astrid.core.project import paths as project_paths
from astrid.core.project.project import create_project
from astrid.core.session import paths as session_paths
from astrid.core.session.binding import ASTRID_SESSION_ID_ENV
from astrid.core.session.identity import Identity, write_identity
from astrid.core.session.model import Session


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv(session_paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "home").mkdir()
    write_identity(Identity(agent_id="claude-1", created_at="2026-05-11T00:00:00Z"))
    return {"home": tmp_path / "home", "projects": tmp_path / "projects"}


def _run_pipeline(argv: list[str]) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    rc = -1
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = pipeline.main(argv)
        except SystemExit as exc:
            # Sub-CLIs (argparse) may sys.exit on bad args. For the gate
            # tests, the important signal is whether the SESSION gate
            # rejected the verb — not whether the downstream parser
            # accepted it. Capture and surface the exit code so the
            # asserts can still distinguish a 'no session bound' rejection
            # (rc==2 with the literal banner in stderr) from any other
            # outcome.
            rc = int(exc.code) if isinstance(exc.code, int) else 2
    return rc, out.getvalue(), err.getvalue()


# ----- gated verbs error without a session ------------------------------


GATED_INVOCATIONS = [
    pytest.param(["doctor"], id="doctor"),
    pytest.param(["setup"], id="setup"),
    pytest.param(["start", "pack.thing", "--project", "demo"], id="start"),
    pytest.param(["next", "--project", "demo"], id="next"),
    pytest.param(["ack", "step", "--project", "demo", "--decision", "approve"], id="ack"),
    pytest.param(["abort", "--project", "demo"], id="abort"),
    pytest.param(["projects", "show", "--project", "demo"], id="projects-show"),
    pytest.param(["projects", "edit", "demo"], id="projects-edit"),
    pytest.param(["runs", "ls"], id="runs-ls"),
    pytest.param(["author", "describe", "pack.thing"], id="author-describe"),
    pytest.param(["executors", "list"], id="executors-list"),
    pytest.param(["orchestrators", "list"], id="orchestrators-list"),
    pytest.param(["elements", "list"], id="elements-list"),
    pytest.param(["audit", "--run", "x"], id="audit"),
]


@pytest.mark.parametrize("argv", GATED_INVOCATIONS)
def test_every_gated_verb_errors_without_session(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    rc, _stdout, stderr = _run_pipeline(argv)
    assert rc == 2
    assert "no session bound" in stderr
    assert "astrid attach" in stderr


# ----- allowlisted verbs run without a session --------------------------


def test_allowlist_status_runs_without_session(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    rc, stdout, _stderr = _run_pipeline(["status"])
    assert rc == 0
    assert "no session bound" in stdout


def test_allowlist_attach_runs_without_session(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    create_project("demo")

    # Seed a default timeline so Sprint 2 resolution works.
    from astrid.core.session.ulid import generate_ulid

    timeline_ulid = generate_ulid()
    pdir = env["projects"] / "demo"
    tdir = pdir / "timelines" / timeline_ulid
    tdir.mkdir(parents=True)
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
    # Update project.json with the default timeline id.
    from astrid.core.project.jsonio import read_json, write_json_atomic

    pp = pdir / "project.json"
    proj = read_json(pp)
    proj["default_timeline_id"] = timeline_ulid
    write_json_atomic(pp, proj)

    rc, stdout, _stderr = _run_pipeline(["attach", "demo"])
    assert rc == 0
    assert "export ASTRID_SESSION_ID=" in stdout


def test_allowlist_projects_ls_runs_without_session(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    rc, _stdout, stderr = _run_pipeline(["projects", "ls"])
    # `projects ls` may not exist as a sub-verb in this repo; the gate is
    # what we're testing, NOT the underlying command. Both 0 and non-zero
    # exit codes are fine — the only forbidden outcome is the gate
    # rejecting the verb.
    assert "no session bound" not in stderr


def test_allowlist_projects_create_runs_without_session(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    rc, _stdout, stderr = _run_pipeline(["projects", "create", "demo"])
    assert rc == 0
    assert "no session bound" not in stderr


def test_allowlist_sessions_ls_runs_without_session(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    rc, _stdout, _stderr = _run_pipeline(["sessions", "ls"])
    assert rc == 0


def test_allowlist_help_runs_without_session(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    rc, stdout, _stderr = _run_pipeline(["--help"])
    assert rc == 0
    assert "Astrid command gateway" in stdout


def test_author_test_with_project_bypasses_gate(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ASTRID_SESSION_ID_ENV, raising=False)
    # The `author test` command itself may fail (missing pack), but the
    # session gate MUST NOT be what fails it. We accept any non-2 'no
    # session bound' outcome.
    rc, _stdout, stderr = _run_pipeline(["author", "test", "pack.thing", "--project", "demo"])
    assert "no session bound" not in stderr


def test_bound_session_lets_gated_verb_through(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mint a minimal session so resolve_current_session succeeds.
    sess = Session(
        id="S-CLI",
        project="demo",
        timeline=None,
        run_id=None,
        agent_id="claude-1",
        attached_at="2026-05-11T00:00:00Z",
        last_used_at="2026-05-11T00:00:00Z",
        role="writer",
    )
    sessions = env["home"] / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sess.to_json(sessions / "S-CLI.json")
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, "S-CLI")

    # `executors list` is a gated verb; it should now pass the gate and
    # produce its own output (the test only cares the gate didn't reject).
    rc, _stdout, stderr = _run_pipeline(["executors", "list"])
    assert "no session bound" not in stderr


def test_bound_session_missing_file_errors_with_hint(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ASTRID_SESSION_ID_ENV, "S-DOES-NOT-EXIST")
    rc, _stdout, stderr = _run_pipeline(["executors", "list"])
    assert rc == 2
    # The SessionBindingError message is what surfaces, not the bare
    # "no session bound" gate hint.
    assert "no session file" in stderr or "session:" in stderr
