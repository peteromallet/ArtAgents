"""T8 (Phase 6): cmd_hook_stop discovery and no-op contract.

Covers both discovery tiers and the silent no-op surface:

(A) Empty no-op: empty projects_root, empty cwd; rc==0, stdout/stderr empty.
(B) Projects-root scan from unrelated cwd (FLAG-P6-001 regression): provision
    a run, capture cmd_next output for the slug, then call cmd_hook_stop
    from a sibling cwd that is NOT inside the projects root; assert hook
    stdout equals the cmd_next capture.
(C) cwd-ancestor walk: same fixture, call cmd_hook_stop with cwd set to the
    project state directory itself; assert hook stdout equals cmd_next.
(D) Negative path: cwd has no active_run.json AND projects_root scan finds
    nothing; rc==0, stdout/stderr empty.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lifecycle_fixtures import setup_run  # noqa: E402

from artagents.core.task.hook import cmd_hook_stop
from artagents.core.task.lifecycle import cmd_next


_BODY_CODE = '''from artagents.orchestrate import orchestrator, code
@orchestrator("demo.code")
def main(): return [code("step_a", argv=["echo", "alpha"])]
'''


def _capture_cmd_next(slug: str, projects_root: Path) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        rc = cmd_next(["--project", slug], projects_root=projects_root)
    assert rc == 0
    return buf.getvalue()


def _capture_hook(*, cwd: Path, projects_root: Path) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_hook_stop([], cwd=cwd, projects_root=projects_root)
    return rc, out.getvalue(), err.getvalue()


def test_empty_projects_root_is_silent_noop(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    cwd = tmp_path / "cwd"
    projects.mkdir()
    cwd.mkdir()
    rc, out, err = _capture_hook(cwd=cwd, projects_root=projects)
    assert rc == 0
    assert out == ""
    assert err == ""


def test_discovers_via_projects_root_scan_from_unrelated_cwd(tmp_path: Path) -> None:
    # FLAG-P6-001 regression: in real Claude Code usage cwd is the user's repo,
    # not the project state directory. The hook MUST discover via projects-root
    # scan and re-print cmd_next output for the active slug.
    packs, projects = setup_run(
        tmp_path, "demo", "code", _BODY_CODE, "demo.code", run_id="r1", project="p"
    )
    expected = _capture_cmd_next("p", projects)

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    rc, out, err = _capture_hook(cwd=unrelated, projects_root=projects)

    assert rc == 0
    assert err == ""
    assert out == expected, "hook stdout must equal cmd_next stdout for the discovered slug"


def test_discovers_via_cwd_ancestor_walk(tmp_path: Path) -> None:
    packs, projects = setup_run(
        tmp_path, "demo", "code", _BODY_CODE, "demo.code", run_id="r2", project="p"
    )
    expected = _capture_cmd_next("p", projects)

    rc, out, err = _capture_hook(cwd=projects / "p", projects_root=projects)

    assert rc == 0
    assert err == ""
    assert out == expected


def test_silent_noop_when_cwd_has_no_run_and_scan_finds_nothing(tmp_path: Path) -> None:
    # Negative path: an empty projects directory (no subdirs at all) plus a
    # cwd that is unrelated and has no active_run.json. Pins the no-op.
    projects = tmp_path / "projects"
    projects.mkdir()
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    (cwd / "some_other_file.txt").write_text("noise", encoding="utf-8")

    rc, out, err = _capture_hook(cwd=cwd, projects_root=projects)
    assert rc == 0
    assert out == ""
    assert err == ""
