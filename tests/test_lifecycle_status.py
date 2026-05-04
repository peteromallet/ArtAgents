"""T16: cmd_status names current step path/run-id/most-recent event kind;
no-active-run prints recovery; no events.jsonl mutation (hash before/after).
"""

from __future__ import annotations

import hashlib
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _lifecycle_fixtures import setup_run  # noqa: E402

from artagents.core.task.events import (
    append_event,
    make_step_completed_event,
    make_step_dispatched_event,
)
from artagents.core.task.lifecycle import cmd_status


_BODY = '''from artagents.orchestrate import orchestrator, code
@orchestrator("demo.app")
def app(): return [
    code("step_a", argv=["echo","a"]),
    code("step_b", argv=["echo","b"]),
]
'''


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_status_names_current_step_run_id_and_recent_event(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "app", _BODY, "demo.app", run_id="r1")
    # Simulate one code-step dispatch by appending step_dispatched + step_completed.
    events_path = projects / "p" / "runs" / "r1" / "events.jsonl"
    append_event(events_path, make_step_dispatched_event("step_a", "echo a"))
    append_event(events_path, make_step_completed_event("step_a", 0))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cmd_status(["--project", "p"], projects_root=projects)
    assert rc == 0
    out = buf.getvalue()
    # Current step is now step_b (cursor advanced past step_a).
    assert "step_b" in out
    assert "r1" in out
    # Most recent event kind is step_completed.
    assert "step_completed" in out


def test_status_no_active_run_prints_recovery(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    err = io.StringIO()
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        rc = cmd_status(["--project", "missing"], projects_root=projects)
    assert rc == 1
    assert "no active run" in err.getvalue()
    assert "artagents start" in err.getvalue()


def test_status_does_not_mutate_events_jsonl(tmp_path: Path) -> None:
    """SC16: the load-bearing 'pure read' assertion."""
    packs, projects = setup_run(tmp_path, "demo", "app", _BODY, "demo.app", run_id="r2")
    events_path = projects / "p" / "runs" / "r2" / "events.jsonl"
    before = _hash_file(events_path)
    with redirect_stdout(io.StringIO()):
        cmd_status(["--project", "p"], projects_root=projects)
        cmd_status(["--project", "p"], projects_root=projects)
    after = _hash_file(events_path)
    assert before == after, "cmd_status must not mutate events.jsonl"
