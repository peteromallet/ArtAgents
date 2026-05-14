"""Tests for project slug uniqueness enforcement at create time."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_second_create_same_slug_exit_code_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Running `astrid projects create` with an existing slug returns exit code 2
    and prints a clear error to stderr."""
    from astrid.core.project import paths

    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))

    # First create succeeds.
    result1 = subprocess.run(
        [sys.executable, "-m", "astrid", "projects", "create", "demo"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent.parent),
    )
    assert result1.returncode == 0, f"first create failed: {result1.stderr}"

    # Second create with the same slug fails.
    result2 = subprocess.run(
        [sys.executable, "-m", "astrid", "projects", "create", "demo"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent.parent),
    )
    assert result2.returncode == 2, (
        f"Expected exit code 2, got {result2.returncode}\n"
        f"stdout: {result2.stdout}\nstderr: {result2.stderr}"
    )
    assert "already exists" in result2.stderr.lower(), (
        f"Expected 'already exists' in stderr, got: {result2.stderr}"
    )


def test_different_roots_are_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same slug can exist under different ASTRID_PROJECTS_ROOT values."""
    from astrid.core.project import paths

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"

    # Create under root A.
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(root_a))
    result_a = subprocess.run(
        [sys.executable, "-m", "astrid", "projects", "create", "demo"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent.parent),
    )
    assert result_a.returncode == 0, f"first create failed: {result_a.stderr}"

    # Create under root B — should succeed since roots are independent.
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(root_b))
    result_b = subprocess.run(
        [sys.executable, "-m", "astrid", "projects", "create", "demo"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent.parent),
    )
    assert result_b.returncode == 0, f"second create under different root failed: {result_b.stderr}"


def test_create_project_unique_slug_direct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the uniqueness check directly via create_project API."""
    from astrid.core.project import paths
    from astrid.core.project.project import ProjectError, create_project

    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))

    # First create succeeds.
    p1 = create_project("demo")
    assert p1["slug"] == "demo"

    # Second create with same slug raises ProjectError.
    with pytest.raises(ProjectError, match="already exists"):
        create_project("demo")

    # exist_ok=True should allow re-entry.
    p2 = create_project("demo", exist_ok=True)
    assert p2["slug"] == "demo"


def test_projects_ls_and_default_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from astrid.core.project import cli, paths
    from astrid.core.project.project import create_project
    from astrid.core.session import paths as session_paths

    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    monkeypatch.setenv(session_paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    create_project("demo")
    create_project("other")

    rc = cli.main(["ls"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "demo" in captured.out
    assert "other" in captured.out

    rc = cli.main(["default", "demo"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "default project (workspace): demo" in captured.out
    assert "python3 -m astrid attach" in captured.out

    rc = cli.main(["default"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "default project: demo" in captured.out

    rc = cli.main(["default", "--clear"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "cleared default project" in captured.out


def test_projects_default_warns_when_configured_default_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from astrid.core.project import cli, paths
    from astrid.core.project.project import create_project
    from astrid.core.session import paths as session_paths

    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    monkeypatch.setenv(session_paths.ASTRID_HOME_ENV, str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    (workspace / ".astrid").mkdir()
    (workspace / ".astrid" / "config.json").write_text('{"default_project": "missing"}', encoding="utf-8")
    create_project("demo")

    rc = cli.main(["default"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "default project: missing" in captured.out
    assert "warning: configured default project is not under the current projects root" in captured.out
    assert "python3 -m astrid projects default demo" in captured.out
