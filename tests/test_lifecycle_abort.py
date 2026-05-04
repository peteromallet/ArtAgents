"""T15: cmd_abort writes run_aborted + clears active_run.json; idempotent
second call returns 0.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _lifecycle_fixtures import setup_run  # noqa: E402

from artagents.core.task.active_run import read_active_run
from artagents.core.task.lifecycle import cmd_abort


_BODY = '''from artagents.orchestrate import orchestrator, code
@orchestrator("demo.app")
def app(): return [code("step_a", argv=["echo", "x"])]
'''


def test_abort_appends_run_aborted_and_clears_active_run(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "app", _BODY, "demo.app", run_id="r1")
    assert read_active_run("p", root=projects) is not None
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cmd_abort(["--project", "p"], projects_root=projects)
    assert rc == 0
    assert read_active_run("p", root=projects) is None
    events = [json.loads(line) for line in (projects/"p"/"runs"/"r1"/"events.jsonl").read_text().splitlines()]
    assert events[-1]["kind"] == "run_aborted"
    assert events[-1]["run_id"] == "r1"
    assert "aborted r1" in buf.getvalue()


def test_second_abort_returns_zero_idempotently(tmp_path: Path) -> None:
    """Phase 6 Stop-hook may invoke abort defensively, so the second call must
    not error.
    """
    packs, projects = setup_run(tmp_path, "demo", "app", _BODY, "demo.app", run_id="r2")
    with redirect_stdout(io.StringIO()):
        rc1 = cmd_abort(["--project", "p"], projects_root=projects)
        rc2 = cmd_abort(["--project", "p"], projects_root=projects)
    assert rc1 == 0
    assert rc2 == 0
    assert read_active_run("p", root=projects) is None
