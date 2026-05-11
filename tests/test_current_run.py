"""Round-trip tests for the per-project current_run pointer (Sprint 1 / T4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.project import paths
from astrid.core.project.current_run import (
    CurrentRunError,
    clear_current_run,
    current_run_path,
    read_current_run,
    write_current_run,
)


def test_read_returns_none_when_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    assert read_current_run("demo") is None


def test_write_and_read_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    written = write_current_run("demo", "01HXYZRUNID")
    assert written == "01HXYZRUNID"
    assert read_current_run("demo") == "01HXYZRUNID"
    # File is atomic JSON.
    on_disk = json.loads(current_run_path("demo").read_text(encoding="utf-8"))
    assert on_disk == {"run_id": "01HXYZRUNID"}


def test_clear_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    write_current_run("demo", "01HXYZRUNID")
    clear_current_run("demo")
    clear_current_run("demo")
    assert read_current_run("demo") is None


def test_read_rejects_malformed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    (tmp_path / "projects" / "demo").mkdir(parents=True)
    current_run_path("demo").write_text(json.dumps({"run_id": ""}), encoding="utf-8")
    with pytest.raises(CurrentRunError, match="run_id"):
        read_current_run("demo")
