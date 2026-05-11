"""Smoke test for the two-tab harness: race two astrid status calls against the same project."""

from __future__ import annotations

from pathlib import Path

from astrid.core.project.project import create_project
from astrid.core.task.active_run import write_active_run
from astrid.core.task.plan import compute_plan_hash, load_plan
from tests.concurrency.two_tab_harness import race_two_tabs


def test_two_concurrent_status_reads_ok(tmp_projects_root: Path) -> None:
    """Race two ``python3 -m astrid status`` calls — both should succeed (reads are safe)."""
    slug = "smoke"

    # Create a project with a plan and active run
    create_project(slug, root=tmp_projects_root)
    plan_path = tmp_projects_root / slug / "plan.json"
    plan_payload = {
        "plan_id": "p1",
        "version": 1,
        "steps": [
            {"id": "step-1", "command": "python3 -c \"print('ok')\""},
        ],
    }
    plan_path.write_text(
        __import__("json").dumps(plan_payload), encoding="utf-8"
    )
    plan = load_plan(plan_path)
    plan_hash = compute_plan_hash(plan_path)
    write_active_run(slug, run_id="run-1", plan_hash=plan_hash, root=tmp_projects_root)

    projects_root = str(tmp_projects_root)

    def setup() -> Path:
        return tmp_projects_root / slug

    result = race_two_tabs(
        setup_fn=setup,
        contended_command=[
            "python3",
            "-m",
            "astrid",
            "status",
            "--project",
            slug,
        ],
        expected_winner_count=2,
        timeout_seconds=30.0,
    )

    assert result.p1_exit_code == 0, f"P1 failed: {result.p1_stderr}"
    assert result.p2_exit_code == 0, f"P2 failed: {result.p2_stderr}"
    assert result.final_disk_state, "Disk state should be captured"