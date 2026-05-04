"""T17: cmd_runs_ls finds runs across projects; --project filters; per
FLAG-P5-006 only 'aborted' and 'in-progress' are observable buckets in V1
(natural completion does not clear active_run.json so 'complete' is not
asserted as observable).
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _lifecycle_fixtures import setup_packs_and_compile  # noqa: E402

from artagents.core.task.lifecycle import cmd_abort, cmd_runs_ls, cmd_start


_BODY_A = '''from artagents.orchestrate import orchestrator, code
@orchestrator("demo.appA")
def app(): return [code("a1", argv=["echo","a1"])]
'''

_BODY_B = '''from artagents.orchestrate import orchestrator, code
@orchestrator("demo.appB")
def app(): return [code("b1", argv=["echo","b1"])]
'''


def _start_one(packs: Path, projects: Path, qid: str, project: str, run_id: str) -> None:
    with redirect_stdout(io.StringIO()):
        cmd_start([qid, "--project", project, "--name", run_id], packs_root=packs, projects_root=projects)


def _abort_one(projects: Path, project: str) -> None:
    with redirect_stdout(io.StringIO()):
        cmd_abort(["--project", project], projects_root=projects)


def test_runs_ls_lists_both_projects(tmp_path: Path) -> None:
    packs, projects = setup_packs_and_compile(tmp_path, "demo", "appA", _BODY_A, "demo.appA")
    # Add second orchestrator into the same pack.
    (packs / "demo" / "appB.py").write_text(_BODY_B, encoding="utf-8")
    from artagents.orchestrate.compile import compile_to_path
    compile_to_path("demo.appB", packs_root=packs)

    # Project alpha: r1 in-progress + r2 aborted.
    _start_one(packs, projects, "demo.appA", "alpha", "r1")
    _abort_one(projects, "alpha")
    _start_one(packs, projects, "demo.appA", "alpha", "r2")
    # leave r2 in-progress

    # Project beta: r3 in-progress + r4 aborted.
    _start_one(packs, projects, "demo.appB", "beta", "r3")
    _abort_one(projects, "beta")
    _start_one(packs, projects, "demo.appB", "beta", "r4")
    # leave r4 in-progress

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cmd_runs_ls([], projects_root=projects)
    assert rc == 0
    out = buf.getvalue()
    # Both projects' runs are present.
    assert "alpha" in out
    assert "beta" in out
    assert "r1" in out and "r2" in out and "r3" in out and "r4" in out
    # Status reflects abort vs in-progress correctly.
    lines = [line for line in out.splitlines() if line.strip()]
    by_run = {line.split("\t")[1]: line for line in lines}
    assert "aborted" in by_run["r1"]
    assert "in-progress" in by_run["r2"]
    assert "aborted" in by_run["r3"]
    assert "in-progress" in by_run["r4"]
    # FLAG-P5-006: 'complete' bucket is mostly unobservable in V1; the lister
    # should NOT emit it for these runs (none reached natural completion AND
    # we haven't manually written run_completed events).
    assert "\tcomplete\t" not in out


def test_runs_ls_project_filter(tmp_path: Path) -> None:
    packs, projects = setup_packs_and_compile(tmp_path, "demo", "appA", _BODY_A, "demo.appA")
    (packs / "demo" / "appB.py").write_text(_BODY_B, encoding="utf-8")
    from artagents.orchestrate.compile import compile_to_path
    compile_to_path("demo.appB", packs_root=packs)
    _start_one(packs, projects, "demo.appA", "alpha", "r1")
    _start_one(packs, projects, "demo.appB", "beta", "r2")
    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_runs_ls(["--project", "alpha"], projects_root=projects)
    out = buf.getvalue()
    assert "alpha" in out and "r1" in out
    assert "beta" not in out and "r2" not in out
