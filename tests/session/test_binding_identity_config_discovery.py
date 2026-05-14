"""Unit tests for the Sprint 1 / T5 session helper modules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.project import paths as project_paths
from astrid.core.project.project import create_project
from astrid.core.session import binding, config, constants, discovery, identity, paths
from astrid.core.session.identity import Identity, IdentityError
from astrid.core.session.lease import write_lease_init
from astrid.core.session.model import Session


def _seed_session(astrid_home: Path, *, sid: str = "S-TEST", project: str = "demo") -> Session:
    sessions = astrid_home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sess = Session(
        id=sid,
        project=project,
        timeline=None,
        run_id=None,
        agent_id="claude-1",
        attached_at="2026-05-11T00:00:00Z",
        last_used_at="2026-05-11T00:00:00Z",
        role="writer",
    )
    sess.to_json(sessions / f"{sid}.json")
    return sess


# ----- binding -----------------------------------------------------------


def test_resolve_current_session_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(binding.ASTRID_SESSION_ID_ENV, raising=False)
    assert binding.resolve_current_session() is None


def test_resolve_current_session_returns_none_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(binding.ASTRID_SESSION_ID_ENV, "")
    assert binding.resolve_current_session() is None


def test_resolve_current_session_loads_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path))
    sess = _seed_session(tmp_path, sid="S-LOAD")
    monkeypatch.setenv(binding.ASTRID_SESSION_ID_ENV, "S-LOAD")
    loaded = binding.resolve_current_session()
    assert loaded is not None
    assert loaded.id == sess.id
    assert loaded.project == sess.project


def test_resolve_current_session_errors_on_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path))
    monkeypatch.setenv(binding.ASTRID_SESSION_ID_ENV, "S-DOES-NOT-EXIST")
    with pytest.raises(binding.SessionBindingError, match="no session file"):
        binding.resolve_current_session()


def test_is_writer_for_matches_lease(tmp_path: Path) -> None:
    sess = Session(
        id="S-1",
        project="demo",
        timeline=None,
        run_id="01RUN",
        agent_id="claude-1",
        attached_at="2026-05-11T00:00:00Z",
        last_used_at="2026-05-11T00:00:00Z",
        role="writer",
    )
    run_dir = tmp_path / "runs" / "01RUN"
    run_dir.mkdir(parents=True)
    write_lease_init(run_dir, session_id=sess.id, plan_hash="")
    assert binding.is_writer_for(sess, run_dir) is True
    # Different session id loses.
    other = Session(**{**sess.to_dict(), "id": "S-OTHER"})
    assert binding.is_writer_for(other, run_dir) is False


def test_current_run_dir_returns_none_when_run_id_unset(tmp_path: Path) -> None:
    sess = _seed_session(tmp_path, sid="S-2")
    assert binding.current_run_dir(sess) is None


def test_current_run_dir_returns_path_when_run_id_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    sess = Session(
        id="S-3",
        project="demo",
        timeline=None,
        run_id="01RUN",
        agent_id="claude-1",
        attached_at="2026-05-11T00:00:00Z",
        last_used_at="2026-05-11T00:00:00Z",
        role="writer",
    )
    rd = binding.current_run_dir(sess)
    assert rd is not None
    assert rd.parts[-3:] == ("demo", "runs", "01RUN")


# ----- identity ----------------------------------------------------------


def test_identity_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path))
    assert identity.read_identity() is None
    identity.write_identity(Identity(agent_id="claude-1", created_at="2026-05-11T00:00:00Z"))
    loaded = identity.read_identity()
    assert loaded == Identity(agent_id="claude-1", created_at="2026-05-11T00:00:00Z")


def test_identity_validate_agent_slug_rejects_bad_input() -> None:
    with pytest.raises(IdentityError):
        identity.validate_agent_slug("Bad Slug!")
    with pytest.raises(IdentityError):
        identity.validate_agent_slug("")
    # Valid:
    assert identity.validate_agent_slug("claude-1") == "claude-1"


def test_bootstrap_identity_persists_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path))
    replies = iter(["claude-1"])

    def fake_prompt(_prompt: str) -> str:
        return next(replies)

    result = identity.bootstrap_identity(prompt=fake_prompt)
    assert result.agent_id == "claude-1"
    on_disk = identity.read_identity()
    assert on_disk is not None
    assert on_disk.agent_id == "claude-1"


def test_bootstrap_identity_reprompts_on_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path))
    replies = iter(["Bad Slug!", "", "claude-1"])

    def fake_prompt(_prompt: str) -> str:
        return next(replies)

    result = identity.bootstrap_identity(prompt=fake_prompt)
    assert result.agent_id == "claude-1"


def test_bootstrap_identity_gives_up_after_three_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path))
    replies = iter(["bad!", "bad!", "bad!"])

    def fake_prompt(_prompt: str) -> str:
        return next(replies)

    with pytest.raises(IdentityError, match="exhausted"):
        identity.bootstrap_identity(prompt=fake_prompt)


def test_bootstrap_identity_noninteractive_eof_is_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path))

    def eof_prompt(_prompt: str) -> str:
        raise EOFError

    with pytest.raises(IdentityError, match="stdin is not interactive"):
        identity.bootstrap_identity(prompt=eof_prompt)


# ----- config ------------------------------------------------------------


def test_config_returns_empty_when_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path))
    assert config.load_user_config() == {}
    assert config.load_workspace_config(tmp_path) == {}
    assert config.resolve_default_project(tmp_path) is None
    assert config.resolve_default_timeline(tmp_path) is None


def test_workspace_config_overrides_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    paths.astrid_home().mkdir(parents=True, exist_ok=True)
    paths.user_config_path().write_text(
        json.dumps({"default_project": "user-pick"}), encoding="utf-8"
    )
    ws_dir = tmp_path / "ws" / ".astrid"
    ws_dir.mkdir(parents=True)
    (ws_dir / "config.json").write_text(
        json.dumps({"default_project": "workspace-pick"}), encoding="utf-8"
    )
    assert config.resolve_default_project(tmp_path / "ws") == "workspace-pick"


def test_set_default_project_writes_workspace_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    ws = tmp_path / "ws"
    path = config.set_default_project("demo", cwd=ws)
    assert path == ws / ".astrid" / "config.json"
    assert config.resolve_default_project(ws) == "demo"
    config.set_default_project(None, cwd=ws)
    assert config.resolve_default_project(ws) is None


def test_config_rejects_non_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.ASTRID_HOME_ENV, str(tmp_path))
    paths.astrid_home().mkdir(parents=True, exist_ok=True)
    paths.user_config_path().write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(config.ConfigError, match="JSON object"):
        config.load_user_config()


# ----- discovery ---------------------------------------------------------


def test_discover_projects_orders_by_mtime_desc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    create_project("alpha")
    create_project("beta")
    create_project("gamma")
    # Bump beta's mtime to make it newest.
    import os
    import time

    now = time.time()
    os.utime(tmp_path / "projects" / "alpha", (now - 100, now - 100))
    os.utime(tmp_path / "projects" / "gamma", (now - 50, now - 50))
    os.utime(tmp_path / "projects" / "beta", (now, now))
    listed = discovery.discover_projects()
    assert listed[0] == "beta"
    # Alpha and gamma in some non-newest order.
    assert set(listed) == {"alpha", "beta", "gamma"}


def test_discover_projects_returns_empty_when_root_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "absent"))
    assert discovery.discover_projects() == []


def test_discover_projects_skips_non_project_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(root))
    (root / "real").mkdir(parents=True)
    (root / "real" / "project.json").write_text("{}", encoding="utf-8")
    (root / "stray").mkdir()  # no project.json
    listed = discovery.discover_projects()
    assert listed == ["real"]


# ----- constants ---------------------------------------------------------


def test_stuck_constants_are_patchable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert constants.STUCK_NO_EVENT_SECONDS == 60
    assert constants.STUCK_SESSION_MTIME_SECONDS == 300
    monkeypatch.setattr(constants, "STUCK_NO_EVENT_SECONDS", 1)
    monkeypatch.setattr(constants, "STUCK_SESSION_MTIME_SECONDS", 2)
    assert constants.STUCK_NO_EVENT_SECONDS == 1
    assert constants.STUCK_SESSION_MTIME_SECONDS == 2
