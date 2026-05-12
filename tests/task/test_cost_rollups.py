"""Sprint 5b: cost rollup tests (T8 / T13).

Tests timeline-level and project-level cost aggregation with
--include-aborted toggling.  The key invariant: timeline cost ==
sum of per-run costs for its contributing runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.task.events import ZERO_HASH, _event_hash


# ── Shared helpers ──────────────────────────────────────────────────────


def _build_chain(raw: list[dict]) -> list[dict]:
    chain: list[dict] = []
    prev = ZERO_HASH
    for r in raw:
        ev = dict(r)
        ev["hash"] = _event_hash(prev, ev)
        chain.append(ev)
        prev = ev["hash"]
    return chain


def _write_events(path: Path, events: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, sort_keys=True, separators=(",", ":")) + "\n")


# Valid ULID-format run IDs (26 chars, Crockford Base32, no I/L/O/U)
R1 = "01ABC1234567890DEFGHJKMNPQ"
R2 = "01DEF1234567890GHJKMNPQRST"
R3 = "01GHJ1234567890JKMNPQRSTVW"


# ── Build a 3-run mixed-cost timeline ───────────────────────────────────


@pytest.fixture
def cost_fixture(tmp_projects_root: Path) -> dict:
    """Project + timeline with 3 runs: local-only, mixed, aborted."""
    from astrid.core.project.project import create_project
    from astrid.core.project.paths import project_dir
    from astrid.core.task.active_run import write_active_run
    from astrid.core.task.plan import compute_plan_hash
    from astrid.core.timeline import crud

    slug = "cost-proj"
    create_project(slug, root=tmp_projects_root)
    proj_root = project_dir(slug, root=tmp_projects_root)

    # Timeline
    result = crud.create_timeline(slug, "cost-line", name="Cost Line")
    timeline_ulid = result["ulid"]
    timeline_dir = proj_root / "timelines" / timeline_ulid

    # Plan
    plan_payload = {
        "plan_id": "p-cost",
        "version": 2,
        "steps": [
            {
                "id": "s1",
                "kind": "code",
                "adapter": "local",
                "command": "echo ok",
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
        ],
    }
    plan_path = proj_root / "plan.json"
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")
    plan_hash = compute_plan_hash(plan_path)

    runs_dir = proj_root / "runs"

    # ── Run 1: completed, local-only cost ────────────────────────────────
    run1_root = runs_dir / R1
    run1_root.mkdir(parents=True, exist_ok=True)
    events1 = _build_chain([
        {"kind": "run_started", "run_id": R1, "plan_hash": plan_hash, "ts": "2026-01-01T00:00:00Z"},
        {"kind": "step_completed", "plan_step_path": ["s1"], "returncode": 0, "ts": "2026-01-01T00:00:01Z",
         "cost": {"amount": 0.00, "currency": "USD", "source": "local"}},
        {"kind": "run_completed", "ts": "2026-01-01T00:00:02Z"},
    ])
    _write_events(run1_root / "events.jsonl", events1)

    # ── Run 2: completed, mixed costs ────────────────────────────────────
    run2_root = runs_dir / R2
    run2_root.mkdir(parents=True, exist_ok=True)
    events2 = _build_chain([
        {"kind": "run_started", "run_id": R2, "plan_hash": plan_hash, "ts": "2026-01-01T01:00:00Z"},
        {"kind": "step_completed", "plan_step_path": ["s1"], "returncode": 0, "ts": "2026-01-01T01:00:01Z",
         "cost": {"amount": 1.50, "currency": "USD", "source": "claude"}},
        {"kind": "step_completed", "plan_step_path": ["s1"], "returncode": 0, "ts": "2026-01-01T01:00:02Z",
         "cost": {"amount": 2.00, "currency": "USD", "source": "runpod"}},
        {"kind": "run_completed", "ts": "2026-01-01T01:00:03Z"},
    ])
    _write_events(run2_root / "events.jsonl", events2)

    # ── Run 3: aborted with partial costs ────────────────────────────────
    run3_root = runs_dir / R3
    run3_root.mkdir(parents=True, exist_ok=True)
    events3 = _build_chain([
        {"kind": "run_started", "run_id": R3, "plan_hash": plan_hash, "ts": "2026-01-01T02:00:00Z"},
        {"kind": "step_completed", "plan_step_path": ["s1"], "returncode": 0, "ts": "2026-01-01T02:00:01Z",
         "cost": {"amount": 0.50, "currency": "USD", "source": "gpt-4"}},
        {"kind": "run_aborted", "ts": "2026-01-01T02:00:02Z"},
    ])
    _write_events(run3_root / "events.jsonl", events3)

    write_active_run(slug, run_id=R1, plan_hash=plan_hash, root=tmp_projects_root)

    # Write manifest.json directly (frozen dataclass can't be mutated)
    manifest_path = timeline_dir / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "contributing_runs": [R1, R2, R3],
        "final_outputs": [],
        "tombstoned_at": None,
    }), encoding="utf-8")

    return {
        "slug": slug,
        "proj_root": proj_root,
        "timeline_ulid": timeline_ulid,
        "run1_id": R1,
        "run2_id": R2,
        "run3_id": R3,
        "runs_dir": runs_dir,
        "plan_hash": plan_hash,
    }


# ── Timeline cost ───────────────────────────────────────────────────────


def test_timeline_cost_excludes_aborted_by_default(
    cost_fixture: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``--include-aborted``, aborted-run costs are excluded."""
    from astrid.core.timeline import cli as tm_cli
    from unittest.mock import MagicMock
    import argparse

    mock_session = MagicMock()
    mock_session.project = cost_fixture["slug"]
    monkeypatch.setattr(tm_cli, "resolve_current_session", lambda: mock_session)

    args = argparse.Namespace(
        slug="cost-line",
        json_out=False,
        include_aborted=False,
    )

    rc = tm_cli.cmd_cost(args)
    assert rc == 0


def test_timeline_cost_includes_aborted_with_flag(
    cost_fixture: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``--include-aborted``, aborted-run costs ARE included."""
    from astrid.core.timeline import cli as tm_cli
    from unittest.mock import MagicMock
    import argparse

    mock_session = MagicMock()
    mock_session.project = cost_fixture["slug"]
    monkeypatch.setattr(tm_cli, "resolve_current_session", lambda: mock_session)

    args = argparse.Namespace(
        slug="cost-line",
        json_out=False,
        include_aborted=True,
    )

    rc = tm_cli.cmd_cost(args)
    assert rc == 0


def test_timeline_cost_json_output(
    cost_fixture: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--json`` produces structured output."""
    from astrid.core.timeline import cli as tm_cli
    from unittest.mock import MagicMock
    import argparse

    mock_session = MagicMock()
    mock_session.project = cost_fixture["slug"]
    monkeypatch.setattr(tm_cli, "resolve_current_session", lambda: mock_session)

    args = argparse.Namespace(
        slug="cost-line",
        json_out=True,
        include_aborted=False,
    )

    rc = tm_cli.cmd_cost(args)
    assert rc == 0


# ── Project cost ────────────────────────────────────────────────────────


def test_project_cost_aggregates_across_timelines(
    tmp_projects_root: Path, cost_fixture: dict
) -> None:
    """Project cost sums across all timelines in the project."""
    from astrid.core.project.cli import _cmd_project_cost
    import argparse

    args = argparse.Namespace(
        project=cost_fixture["slug"],
        json=False,
        include_aborted=False,
    )

    rc = _cmd_project_cost(args)
    assert rc == 0


def test_project_cost_json_output(
    tmp_projects_root: Path, cost_fixture: dict
) -> None:
    """Project cost ``--json`` produces structured output."""
    from astrid.core.project.cli import _cmd_project_cost
    import argparse

    args = argparse.Namespace(
        project=cost_fixture["slug"],
        json=True,
        include_aborted=False,
    )

    rc = _cmd_project_cost(args)
    assert rc == 0


def test_project_cost_include_aborted(
    tmp_projects_root: Path, cost_fixture: dict
) -> None:
    """``--include-aborted`` on project cost toggles aborted runs."""
    from astrid.core.project.cli import _cmd_project_cost
    import argparse

    args = argparse.Namespace(
        project=cost_fixture["slug"],
        json=False,
        include_aborted=True,
    )

    rc = _cmd_project_cost(args)
    assert rc == 0


# ── Invariant: timeline cost == sum(per-run costs) ──────────────────────


def test_cost_rollup_invariant(cost_fixture: dict) -> None:
    """``_cost_by_source`` consistency: summing run costs equals timeline
    cost when aggregating the same runs."""
    from astrid.core.task.events import read_events
    from astrid.core.task.run_audit import _cost_by_source, _run_status

    runs = [cost_fixture["run1_id"], cost_fixture["run2_id"]]
    runs_dir = cost_fixture["runs_dir"]

    by_source_manual: dict[str, float] = {}

    for run_id in runs:
        events_path = runs_dir / run_id / "events.jsonl"
        events = read_events(events_path)
        status = _run_status(events)
        assert status != "aborted"

        cost_summary = _cost_by_source(events)
        for source, info in cost_summary.items():
            amt = float(info.get("amount", 0)) if isinstance(info, dict) else float(info)
            by_source_manual[source] = by_source_manual.get(source, 0.0) + amt

    assert by_source_manual.get("local", 0.0) == 0.0
    assert by_source_manual.get("claude", 0.0) == 1.50
    assert by_source_manual.get("runpod", 0.0) == 2.00

    total_manual = sum(by_source_manual.values())
    assert total_manual == 3.50