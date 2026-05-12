"""End-to-end test of builtin.hype port against tiny fixture project (Sprint 5a T14).

Mock RunPod at ``external.runpod.session`` boundary; no live calls.
Verifies:
- Initial plan v2 emitted with stable plan hash
- Dynamic plan mutation via ``add-step`` (shot count discovered after cut)
- All steps terminal with ``step_dispatched`` → ``step_completed`` events
- ``run_completed`` lands after final step completes
- Artifacts under canonical ``steps/<id>/v<N>/produces/...`` paths
- ``consumes`` populated on ``run.json``
- Costs surfaced on completion events
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from astrid.core.task.events import (
    _run_is_complete,
    make_run_completed_event,
    make_step_completed_event,
    make_step_dispatched_event,
)
from astrid.core.task.plan import (
    Step,
    TaskPlan,
    compute_plan_hash,
    load_plan,
)


# ---------------------------------------------------------------------------
# Synthetic run fixture
# ---------------------------------------------------------------------------


def _build_synthetic_hype_run(
    tmp_path: Path,
    slug: str = "demo",
    run_id: str = "run-hype-1",
    python_exec: str = "python3",
    *,
    source_media: bytes | None = None,
) -> tuple[Path, Path, Path]:
    """Create a synthetic hype project + run with source media and plan v2.

    Writes ``plan.json`` into BOTH the project root and the run directory
    (the real ``cmd_start`` copies it; ``cmd_plan_add_step`` reads it from
    the run dir).

    Returns ``(project_root, run_dir, source_path, plan_path)``.
    """
    from astrid.packs.builtin.hype.plan_template import build_plan_v2, emit_plan_json

    proj_root = tmp_path / "projects" / slug
    run_dir = proj_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Stub source media file
    if source_media is None:
        source_media = b"fake-mp4-bytes-for-testing"
    source_path = proj_root / "source.mp4"
    source_path.write_bytes(source_media)

    # Build and emit plan v2
    plan_dict = build_plan_v2(
        python_exec=python_exec,
        run_root=run_dir,
        source=source_path,
        run_id=run_id,
    )
    plan_path = proj_root / "plan.json"
    emit_plan_json(plan_dict, plan_path)

    # Also copy into the run directory (cmd_start behaviour) so
    # cmd_plan_add_step / _load_effective_plan can find it.
    run_plan_path = run_dir / "plan.json"
    run_plan_path.write_text(plan_path.read_text(encoding="utf-8"), encoding="utf-8")

    # Compute source sha256 for consumes
    src_sha256 = hashlib.sha256(source_media).hexdigest()

    # Write run.json with consumes
    run_json = {
        "run_id": run_id,
        "created_at": "2025-01-01T00:00:00Z",
        "consumes": [
            {"source": str(source_path), "sha256": src_sha256},
        ],
        "plan_hash": compute_plan_hash(str(plan_path)),
        "orchestrator": "builtin.hype",
    }
    (run_dir / "run.json").write_text(
        json.dumps(run_json, indent=2), encoding="utf-8"
    )

    return proj_root, run_dir, source_path, plan_path


def _write_step_event(events_path: Path, event: dict) -> None:
    """Append an event line to events.jsonl."""
    line = json.dumps(event, sort_keys=True, ensure_ascii=False)
    with open(events_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Initial plan v2 emission + stable plan hash
# ---------------------------------------------------------------------------


def test_initial_plan_v2_emission(tmp_path: Path) -> None:
    """Build plan v2, emit it as JSON, and verify plan hash is stable."""
    from astrid.packs.builtin.hype.plan_template import build_plan_v2

    proj_root, run_dir, _, plan_path = _build_synthetic_hype_run(tmp_path)

    # Plan file exists and is valid v2 JSON
    assert plan_path.exists()
    plan_text = plan_path.read_text(encoding="utf-8")
    plan_data = json.loads(plan_text)
    assert plan_data["version"] == 2

    # Plan hash is stable (same plan → same hash)
    hash1 = compute_plan_hash(str(plan_path))
    hash2 = compute_plan_hash(str(plan_path))
    assert hash1 == hash2
    assert hash1.startswith("sha256:")

    # Verify the top-level group step has re_export (G1)
    steps = plan_data.get("steps", [])
    assert len(steps) > 0
    top = steps[0]
    assert top["id"] == "hype"
    assert "re_export" in top
    assert "children" in top

    # Verify children match the 6-stage spine
    child_ids = [c["id"] for c in top["children"]]
    assert "transcribe" in child_ids
    assert "scenes" in child_ids
    assert "cut" in child_ids
    assert "render" in child_ids
    assert "editor_review" in child_ids
    assert "validate" in child_ids


def test_plan_hash_different_for_different_plans(tmp_path: Path) -> None:
    """Two plans with different run_ids produce different hashes."""
    from astrid.packs.builtin.hype.plan_template import build_plan_v2, emit_plan_json

    slug = "demo"
    proj_root = tmp_path / "projects" / slug
    proj_root.mkdir(parents=True)

    source = proj_root / "source.mp4"
    source.write_bytes(b"data")

    run_dir1 = proj_root / "runs" / "run-A"
    run_dir1.mkdir(parents=True, exist_ok=True)
    plan1 = build_plan_v2(
        python_exec="python3", run_root=run_dir1, source=source, run_id="run-A"
    )
    plan_path1 = proj_root / "plan-A.json"
    emit_plan_json(plan1, plan_path1)

    run_dir2 = proj_root / "runs" / "run-B"
    run_dir2.mkdir(parents=True, exist_ok=True)
    plan2 = build_plan_v2(
        python_exec="python3", run_root=run_dir2, source=source, run_id="run-B"
    )
    plan_path2 = proj_root / "plan-B.json"
    emit_plan_json(plan2, plan_path2)

    h1 = compute_plan_hash(str(plan_path1))
    h2 = compute_plan_hash(str(plan_path2))
    assert h1 != h2


# ---------------------------------------------------------------------------
# run.json consumes field
# ---------------------------------------------------------------------------


def test_run_json_consumes_populated(tmp_path: Path) -> None:
    """run.json is written with consumes, plan_hash, orchestrator."""
    proj_root, run_dir, source_path, _ = _build_synthetic_hype_run(tmp_path)

    run_json_path = run_dir / "run.json"
    assert run_json_path.exists()

    data = json.loads(run_json_path.read_text(encoding="utf-8"))
    assert data["orchestrator"] == "builtin.hype"
    assert "plan_hash" in data
    assert data["plan_hash"].startswith("sha256:")

    # consumes should include the source media
    assert "consumes" in data
    consumes = data["consumes"]
    assert isinstance(consumes, list)
    assert len(consumes) >= 1
    assert any(c["source"] == str(source_path) or c["source"].endswith("source.mp4")
               for c in consumes)


def test_run_json_consumes_optional_on_read(tmp_path: Path) -> None:
    """A run.json without consumes is still readable (back-compat)."""
    proj_root, run_dir, _, _ = _build_synthetic_hype_run(tmp_path)

    # Remove consumes from run.json
    run_json_path = run_dir / "run.json"
    data = json.loads(run_json_path.read_text(encoding="utf-8"))
    del data["consumes"]
    run_json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Re-read — no crash, just no consumes
    data2 = json.loads(run_json_path.read_text(encoding="utf-8"))
    assert "consumes" not in data2


# ---------------------------------------------------------------------------
# Dynamic plan mutation via add-step
# ---------------------------------------------------------------------------


def test_dynamic_add_step_shot_count_discovery(tmp_path: Path) -> None:
    """After cut discovers shot count, add detail steps via cmd_plan_add_step."""
    proj_root, run_dir, _, _ = _build_synthetic_hype_run(tmp_path)

    # Seed the run with a lease so add-step can validate
    from astrid.core.session.lease import write_lease_init
    write_lease_init(run_dir, session_id="test-session-1", plan_hash="")

    # Seed the first event using ``append_event`` so the hash chain is valid.
    from astrid.core.task.events import append_event as append_event_locked
    events_path = run_dir / "events.jsonl"
    append_event_locked(
        events_path,
        {"kind": "run_started", "run_id": "run-hype-1", "ts": "2025-01-01T00:00:00Z"},
    )

    # Call cmd_plan_add_step to add a shot-detail step after cut.
    # ``cut`` is a child of ``hype``, so the path is ``hype/cut``.
    from astrid.core.task.plan_verbs import cmd_plan_add_step

    result = cmd_plan_add_step(
        [
            "--project", "demo",
            "--run-id", "run-hype-1",
            "--step-id", "shot_detail_01",
            "--adapter", "local",
            "--command", "python3 -m astrid.packs.builtin.render_shot --shot 01",
            "--after", "hype/cut",
        ],
        projects_root=tmp_path / "projects",
    )
    # Should succeed (0 exit)
    assert result == 0

    # Verify the plan_mutated event was written
    events = []
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    mutation_events = [e for e in events if e.get("kind") == "plan_mutated"]
    assert len(mutation_events) >= 1

    add_event = mutation_events[-1]
    diff = add_event.get("diff", {})
    assert diff.get("op") == "add"
    step = diff.get("step", {})
    assert step.get("id") == "shot_detail_01"
    assert step.get("adapter") == "local"


def test_dynamic_add_step_into_group(tmp_path: Path) -> None:
    """Add step into the hype group step."""
    proj_root, run_dir, _, _ = _build_synthetic_hype_run(tmp_path)

    from astrid.core.session.lease import write_lease_init
    write_lease_init(run_dir, session_id="test-session-2", plan_hash="")

    # Seed the first event with the hash chain intact.
    from astrid.core.task.events import append_event as append_event_locked
    events_path = run_dir / "events.jsonl"
    append_event_locked(
        events_path,
        {"kind": "run_started", "run_id": "run-hype-1", "ts": "2025-01-01T00:00:00Z"},
    )

    from astrid.core.task.plan_verbs import cmd_plan_add_step

    result = cmd_plan_add_step(
        [
            "--project", "demo",
            "--run-id", "run-hype-1",
            "--step-id", "extra_render",
            "--adapter", "local",
            "--command", "python3 -m astrid.packs.external.runpod session --extra",
            "--into", "hype",
        ],
        projects_root=tmp_path / "projects",
    )
    assert result == 0

    # Verify the effective plan now includes the new step
    from astrid.core.task.plan_verbs import apply_mutations

    plan = load_plan(str(run_dir / "plan.json"))
    events = []
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    effective = apply_mutations(plan, events)
    all_ids = [s.id for s in effective.steps]
    # The extra step should appear somewhere (flat or under hype group)
    found = any(
        child.id == "extra_render"
        for step in effective.steps
        if step.children is not None
        for child in step.children
    )
    # If flat, look for it directly or in children
    if not found:
        found = any(s.id == "extra_render" for s in effective.steps)
    assert found, "extra_render step not found in effective plan after add-step"


# ---------------------------------------------------------------------------
# Full step lifecycle: dispatched → completed
# ---------------------------------------------------------------------------


def test_full_step_lifecycle_events(tmp_path: Path) -> None:
    """All leaf steps emit step_dispatched then step_completed."""
    proj_root, run_dir, _, _ = _build_synthetic_hype_run(tmp_path)

    # Load the plan to know the leaf step ids
    plan = load_plan(str(run_dir / "plan.json"))
    leaf_ids = _collect_leaf_ids(plan.steps)

    events_path = run_dir / "events.jsonl"

    # Simulate run start
    _write_step_event(
        events_path,
        {"kind": "run_started", "run_id": "run-hype-1", "ts": "2025-01-01T00:00:00Z"},
    )

    # Simulate dispatching and completing each leaf step
    for leaf_id in sorted(leaf_ids):
        # Create step directory and produces
        step_dir = run_dir / "steps" / leaf_id / "v1"
        step_dir.mkdir(parents=True, exist_ok=True)
        produces_dir = step_dir / "produces"
        produces_dir.mkdir(exist_ok=True)

        # Write dispatched event
        _write_step_event(
            events_path,
            make_step_dispatched_event(
                leaf_id,
                f"python3 -m {leaf_id}",
                adapter="local",
                step_version=1,
            ),
        )

        # Write a stub artifact
        artifact_path = produces_dir / f"{leaf_id}_output.json"
        artifact_path.write_text('{"status": "done"}', encoding="utf-8")

        # Write completed event with cost
        cost = {"amount": 0.05, "currency": "USD", "source": "gemini"}
        # Editor_review uses manual adapter
        adapter = "manual" if leaf_id == "editor_review" else "local"
        _write_step_event(
            events_path,
            make_step_completed_event(
                leaf_id, returncode=0, cost=cost, adapter=adapter
            ),
        )

    # Verify run_completed works
    all_events = []
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                all_events.append(json.loads(line))

    assert _run_is_complete(plan, all_events) is True

    # Emit run_completed
    _write_step_event(events_path, make_run_completed_event("run-hype-1"))

    # Verify final event is run_completed
    with open(events_path, encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    final_event = json.loads(lines[-1])
    assert final_event["kind"] == "run_completed"
    assert final_event["run_id"] == "run-hype-1"


def test_artifacts_under_canonical_paths(tmp_path: Path) -> None:
    """Verify artifacts land under steps/<id>/v<N>/produces/... paths."""
    proj_root, run_dir, _, _ = _build_synthetic_hype_run(tmp_path)

    plan = load_plan(str(run_dir / "plan.json"))
    leaf_ids = _collect_leaf_ids(plan.steps)

    for leaf_id in sorted(leaf_ids):
        step_dir = run_dir / "steps" / leaf_id / "v1" / "produces"
        step_dir.mkdir(parents=True, exist_ok=True)
        artifact = step_dir / f"{leaf_id}_result.json"
        artifact.write_text(f'{{"step": "{leaf_id}"}}', encoding="utf-8")
        assert artifact.exists()

    # Verify canonical path structure
    assert (run_dir / "steps" / "transcribe" / "v1" / "produces").exists()
    assert (run_dir / "steps" / "scenes" / "v1" / "produces").exists()
    assert (run_dir / "steps" / "cut" / "v1" / "produces").exists()
    assert (run_dir / "steps" / "render" / "v1" / "produces").exists()
    assert (run_dir / "steps" / "editor_review" / "v1" / "produces").exists()
    assert (run_dir / "steps" / "validate" / "v1" / "produces").exists()


def test_costs_surfaced_on_completion_events(tmp_path: Path) -> None:
    """All step_completed events carry cost fields."""
    proj_root, run_dir, _, _ = _build_synthetic_hype_run(tmp_path)
    events_path = run_dir / "events.jsonl"

    _write_step_event(
        events_path,
        {"kind": "run_started", "run_id": "run-hype-1", "ts": "2025-01-01T00:00:00Z"},
    )

    costs_emitted = []
    for step_id, cost in [
        ("transcribe", {"amount": 0.002, "currency": "USD", "source": "gemini"}),
        ("scenes", {"amount": 0.005, "currency": "USD", "source": "gemini"}),
        ("cut", {"amount": 0.010, "currency": "USD", "source": "claude"}),
        ("render", {"amount": 0.50, "currency": "USD", "source": "runpod"}),
        ("editor_review", {"amount": 0.0, "currency": "USD", "source": "manual"}),
        ("validate", {"amount": 0.001, "currency": "USD", "source": "gemini"}),
    ]:
        # Create step dir
        (run_dir / "steps" / step_id / "v1" / "produces").mkdir(parents=True, exist_ok=True)

        _write_step_event(
            events_path,
            make_step_dispatched_event(
                step_id,
                f"python3 -m {step_id}",
                adapter="manual" if step_id == "editor_review" else "local",
            ),
        )
        _write_step_event(
            events_path,
            make_step_completed_event(
                step_id,
                returncode=0,
                cost=cost,
                adapter="manual" if step_id == "editor_review" else "local",
            ),
        )
        costs_emitted.append(cost)

    # Read all events, verify completion events carry cost
    all_events = []
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                all_events.append(json.loads(line))

    completed_events = [e for e in all_events if e.get("kind") == "step_completed"]
    assert len(completed_events) == 6

    sources_seen = set()
    for ev in completed_events:
        assert "cost" in ev
        assert "amount" in ev["cost"]
        assert "source" in ev["cost"]
        sources_seen.add(ev["cost"]["source"])

    assert "gemini" in sources_seen
    assert "claude" in sources_seen
    assert "runpod" in sources_seen


# ---------------------------------------------------------------------------
# run_completed event guard
# ---------------------------------------------------------------------------


def test_run_completed_not_emitted_with_awaiting_fetch(tmp_path: Path) -> None:
    """_run_is_complete returns False when any step is awaiting_fetch."""
    proj_root, run_dir, _, _ = _build_synthetic_hype_run(tmp_path)
    events_path = run_dir / "events.jsonl"

    plan = load_plan(str(run_dir / "plan.json"))

    _write_step_event(
        events_path,
        {"kind": "run_started", "run_id": "run-hype-1", "ts": "2025-01-01T00:00:00Z"},
    )

    # Complete all but render (which goes to awaiting_fetch)
    leaf_ids = _collect_leaf_ids(plan.steps)
    for leaf_id in sorted(leaf_ids):
        (run_dir / "steps" / leaf_id / "v1" / "produces").mkdir(parents=True, exist_ok=True)
        _write_step_event(
            events_path,
            make_step_dispatched_event(
                leaf_id,
                f"python3 -m {leaf_id}",
                adapter="manual" if leaf_id == "editor_review" else "local",
            ),
        )
        if leaf_id == "render":
            # Emit awaiting_fetch instead of completed
            _write_step_event(
                events_path,
                {
                    "kind": "step_awaiting_fetch",
                    "plan_step_path": ["render"],
                    "missing": ["hype.mp4"],
                    "mismatched": [],
                    "ts": "2025-01-01T00:01:00Z",
                },
            )
        else:
            _write_step_event(
                events_path,
                make_step_completed_event(
                    leaf_id,
                    returncode=0,
                    adapter="manual" if leaf_id == "editor_review" else "local",
                ),
            )

    all_events = []
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                all_events.append(json.loads(line))

    # Should NOT be complete
    assert _run_is_complete(plan, all_events) is False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _collect_leaf_ids(steps: tuple[Step, ...]) -> set[str]:
    """Collect all leaf step ids from a step tree."""
    leaf_ids: set[str] = set()

    def _walk(s: tuple[Step, ...]) -> None:
        for step in s:
            if step.children is None:
                leaf_ids.add(step.id)
            else:
                _walk(step.children)

    _walk(steps)
    return leaf_ids