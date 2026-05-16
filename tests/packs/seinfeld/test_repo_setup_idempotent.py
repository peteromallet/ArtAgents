"""Second invocation of repo_setup is a no-op when submodule .git exists."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from astrid.packs.seinfeld.executors.repo_setup import run as setup_run


def test_idempotent_second_invocation_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pretend the repo root is tmp_path and the submodule is already initialised.
    fake_root = tmp_path
    submodule = fake_root / setup_run.SUBMODULE_PATH
    (submodule / ".git").mkdir(parents=True)

    monkeypatch.setattr(setup_run, "_repo_root", lambda: fake_root)

    # If git is actually invoked, the test will fail because we don't want it
    # to touch a real repo. Make subprocess.run a guard.
    called: list[list[str]] = []
    orig_run = subprocess.run

    def guard(*args, **kwargs):  # type: ignore[no-untyped-def]
        argv = args[0] if args else kwargs.get("args")
        called.append(list(argv) if argv else [])
        raise AssertionError(f"subprocess.run unexpectedly called: {argv}")

    monkeypatch.setattr(setup_run.subprocess, "run", guard)

    produces = tmp_path / "produces"
    rc = setup_run.main(["--produces-dir", str(produces)])
    assert rc == 0
    assert called == [], f"git was invoked: {called}"

    result = json.loads((produces / "setup_result.json").read_text(encoding="utf-8"))
    assert result["status"] == "already_initialized"
    assert result["sha"] == setup_run.PINNED_SHA
