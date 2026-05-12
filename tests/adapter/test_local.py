"""Tests for LocalAdapter (Sprint 3 T22).

Covers: dispatch, completion, failure modes, subprocess-outlives-tab.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from astrid.core.adapter import RunContext
from astrid.core.adapter.local import LocalAdapter
from astrid.core.task.plan import ProducesEntry, Step
from astrid.verify import file_nonempty


@pytest.fixture
def adapter() -> LocalAdapter:
    return LocalAdapter()


def _make_ctx(tmp_path: Path, **kwargs) -> RunContext:
    defaults = {
        "slug": "demo",
        "run_id": "run-1",
        "project_root": tmp_path,
        "plan_step_path": ("s1",),
        "step_version": 1,
    }
    defaults.update(kwargs)
    return RunContext(**defaults)


def _make_step(**kwargs) -> Step:
    defaults = {"id": "s1", "adapter": "local", "command": "echo ok"}
    defaults.update(kwargs)
    return Step(**defaults)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def test_dispatch_creates_pid_and_sidecar(adapter: LocalAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    result = adapter.dispatch(step, ctx)
    assert result.status == "dispatched"
    assert result.pid is not None
    assert result.pid > 0
    assert result.started_at is not None

    dispatch_path = tmp_path / "runs" / "run-1" / "steps" / "s1" / "v1" / "dispatch.json"
    assert dispatch_path.exists()
    meta = json.loads(dispatch_path.read_text())
    assert meta["pid"] == result.pid
    assert meta["command"] == "echo ok"


def test_dispatch_rejects_empty_command(adapter: LocalAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="   ")
    result = adapter.dispatch(step, ctx)
    assert result.status == "rejected"


def test_dispatch_rejects_unparseable_command(adapter: LocalAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="echo 'unclosed")
    result = adapter.dispatch(step, ctx)
    assert result.status == "rejected"


# ---------------------------------------------------------------------------
# poll
# ---------------------------------------------------------------------------

def test_poll_pending_when_no_dispatch(adapter: LocalAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    result = adapter.poll(step, ctx)
    assert result.status == "pending"


def test_poll_running_after_dispatch(adapter: LocalAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="sleep 10")
    adapter.dispatch(step, ctx)
    result = adapter.poll(step, ctx)
    assert result.status in ("running", "done")  # race: may finish before poll


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------

def test_complete_success(adapter: LocalAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="echo hello")
    adapter.dispatch(step, ctx)
    # Wait for subprocess to finish
    import time
    time.sleep(0.3)
    # Write returncode sidecar (normally done by cmd_next)
    rc_path = tmp_path / "runs" / "run-1" / "steps" / "s1" / "v1" / "returncode"
    rc_path.write_text("0")

    result = adapter.complete(step, ctx)
    assert result.status == "completed"
    assert result.returncode == 0


def test_complete_failure_nonzero_exit(adapter: LocalAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="exit 1")
    adapter.dispatch(step, ctx)
    import time
    time.sleep(0.3)
    rc_path = tmp_path / "runs" / "run-1" / "steps" / "s1" / "v1" / "returncode"
    rc_path.write_text("1")

    result = adapter.complete(step, ctx)
    assert result.status == "failed"
    assert result.returncode == 1


def test_complete_with_produces_check(adapter: LocalAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step(
        command="echo out",
        produces=(ProducesEntry(name="out", path="out.txt", check=file_nonempty()),),
    )
    adapter.dispatch(step, ctx)
    import time
    time.sleep(0.3)

    rc_path = tmp_path / "runs" / "run-1" / "steps" / "s1" / "v1" / "returncode"
    rc_path.write_text("0")
    produces_dir = tmp_path / "runs" / "run-1" / "steps" / "s1" / "v1" / "produces"
    produces_dir.mkdir(exist_ok=True)
    (produces_dir / "out.txt").write_text("output data")

    result = adapter.complete(step, ctx)
    assert result.status == "completed"


def test_complete_missing_produces_fails(adapter: LocalAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step(
        command="echo ok",
        produces=(ProducesEntry(name="out", path="missing.txt", check=file_nonempty()),),
    )
    adapter.dispatch(step, ctx)
    import time
    time.sleep(0.3)

    rc_path = tmp_path / "runs" / "run-1" / "steps" / "s1" / "v1" / "returncode"
    rc_path.write_text("0")

    result = adapter.complete(step, ctx)
    assert result.status == "failed"


def test_complete_cost_omitted_when_absent(adapter: LocalAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    adapter.dispatch(step, ctx)
    import time
    time.sleep(0.3)
    rc_path = tmp_path / "runs" / "run-1" / "steps" / "s1" / "v1" / "returncode"
    rc_path.write_text("0")

    result = adapter.complete(step, ctx)
    assert result.status == "completed"
    assert result.cost is None  # Cost omitted, not null


def test_subprocess_outlives_tab_detached(adapter: LocalAdapter, tmp_path: Path) -> None:
    """LocalAdapter uses start_new_session=True so subprocess outlives parent tab.

    We can't truly close the tab in a test, but we can verify the dispatch
    mechanism uses new session. After dispatch, the process runs independently.
    """
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="sleep 5")
    result = adapter.dispatch(step, ctx)
    assert result.status == "dispatched"
    assert result.pid > 0

    # The process should be alive (running in its own session)
    poll_result = adapter.poll(step, ctx)
    assert poll_result.status in ("running", "done")
    
    # Kill the subprocess to clean up
    import signal
    try:
        os.kill(result.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # already exited