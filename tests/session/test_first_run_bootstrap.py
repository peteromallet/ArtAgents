"""First-run status remains discoverable even when identity is absent."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

import pytest

from astrid.core.project import paths as project_paths
from astrid.core.session import cli, paths as session_paths
from astrid.core.session.identity import read_identity


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv(session_paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    monkeypatch.setenv(project_paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    monkeypatch.delenv("ASTRID_SESSION_ID", raising=False)
    return {"home": tmp_path / "home", "projects": tmp_path / "projects"}


def test_status_does_not_bootstrap_when_identity_absent(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # No identity file exists.
    assert read_identity() is None

    def _trap(_prompt: str) -> str:  # pragma: no cover - asserted by exception
        raise AssertionError("status should not prompt for identity")

    monkeypatch.setattr("builtins.input", _trap)
    buf = StringIO()
    rc = cli.cmd_status(argparse.Namespace(), out=buf)
    assert rc == 0
    output = buf.getvalue()
    assert cli.FIRST_RUN_PROMPT_HEADER not in output
    assert cli.STATUS_UNBOUND_HEADER in output
    assert read_identity() is None


def test_status_does_not_bootstrap_when_identity_present(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed an identity.
    (env["home"]).mkdir(parents=True, exist_ok=True)
    (env["home"] / "identity.json").write_text(
        '{"agent_id":"codex-1","created_at":"2026-05-11T00:00:00Z"}',
        encoding="utf-8",
    )
    # input() must NOT be called now.
    called = {"yes": False}

    def _trap(_prompt: str) -> str:  # pragma: no cover - asserted via flag
        called["yes"] = True
        return "x"

    monkeypatch.setattr("builtins.input", _trap)
    rc = cli.cmd_status(argparse.Namespace(), out=StringIO())
    assert rc == 0
    assert called["yes"] is False
