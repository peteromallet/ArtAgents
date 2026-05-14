"""T12: cmd_start writes active_run.json + AGENT.md + run_started; second
start rejected; missing build/<name>.json prints compile recovery + rc=1.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _lifecycle_fixtures import make_pack, setup_packs_and_compile  # noqa: E402

from astrid.core.task.active_run import read_active_run
from astrid.core.task.lifecycle import cmd_start
from astrid.core.task.plan import compute_plan_hash
from astrid.core.task.preamble import PROHIBITION_PREAMBLE
from astrid.core.project.project import create_project


_BODY_CODE = '''from astrid.orchestrate import orchestrator, code
@orchestrator("demo.app")
def app(): return [code("step_a", argv=["echo", "x"])]
'''


def test_start_writes_active_run_with_correct_hash(tmp_path: Path) -> None:
    packs, projects = setup_packs_and_compile(tmp_path, "demo", "app", _BODY_CODE, "demo.app")
    create_project("p", root=projects)
    rc = cmd_start(
        ["demo.app", "--project", "p", "--name", "r1"],
        packs_root=packs,
        projects_root=projects,
    )
    assert rc == 0
    active = read_active_run("p", root=projects)
    assert active is not None
    assert active["run_id"] == "r1"
    plan_hash = compute_plan_hash(projects / "p" / "plan.json")
    assert active["plan_hash"] == plan_hash


def test_events_jsonl_first_line_is_run_started(tmp_path: Path) -> None:
    packs, projects = setup_packs_and_compile(tmp_path, "demo", "app", _BODY_CODE, "demo.app")
    create_project("p", root=projects)
    cmd_start(["demo.app", "--project", "p", "--name", "r2"], packs_root=packs, projects_root=projects)
    events_path = projects / "p" / "runs" / "r2" / "events.jsonl"
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert lines, "events.jsonl must have at least one line"
    first = json.loads(lines[0])
    assert first["kind"] == "run_started"
    assert first["run_id"] == "r2"


def test_agent_md_includes_preamble(tmp_path: Path) -> None:
    packs, projects = setup_packs_and_compile(tmp_path, "demo", "app", _BODY_CODE, "demo.app")
    create_project("p", root=projects)
    cmd_start(["demo.app", "--project", "p", "--name", "r3"], packs_root=packs, projects_root=projects)
    agent_md = (projects / "p" / "runs" / "r3" / "AGENT.md").read_text(encoding="utf-8")
    assert PROHIBITION_PREAMBLE in agent_md
    assert "demo.app" in agent_md
    assert "r3" in agent_md


def test_second_start_rejected_with_recovery(tmp_path: Path) -> None:
    packs, projects = setup_packs_and_compile(tmp_path, "demo", "app", _BODY_CODE, "demo.app")
    create_project("p", root=projects)
    cmd_start(["demo.app", "--project", "p", "--name", "r4"], packs_root=packs, projects_root=projects)
    err = io.StringIO()
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        rc = cmd_start(
            ["demo.app", "--project", "p"],
            packs_root=packs,
            projects_root=projects,
        )
    assert rc == 1
    msg = err.getvalue()
    assert "active run already exists" in msg
    assert "astrid abort --project p" in msg


def test_missing_build_json_prints_compile_recovery(tmp_path: Path) -> None:
    # Pack exists but we never compile; build/<name>.json is absent.
    packs = tmp_path / "packs"
    projects = tmp_path / "projects"
    packs.mkdir()
    projects.mkdir()
    make_pack(packs, "demo", "uncompiled", _BODY_CODE.replace("demo.app", "demo.uncompiled"))
    create_project("q", root=projects)
    err = io.StringIO()
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        rc = cmd_start(
            ["demo.uncompiled", "--project", "q"],
            packs_root=packs,
            projects_root=projects,
        )
    assert rc == 1
    assert "astrid author compile demo.uncompiled" in err.getvalue()


def test_start_rejects_missing_project_before_creating_run_dir(tmp_path: Path) -> None:
    packs, projects = setup_packs_and_compile(tmp_path, "demo", "app", _BODY_CODE, "demo.app")
    err = io.StringIO()
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        rc = cmd_start(
            ["demo.app", "--project", "missing"],
            packs_root=packs,
            projects_root=projects,
        )
    assert rc == 1
    assert "project 'missing' not found" in err.getvalue()
    assert not (projects / "missing" / "runs").exists()
