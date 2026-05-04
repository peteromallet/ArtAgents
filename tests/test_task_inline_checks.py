from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from artagents.core.project.project import create_project
from artagents.core.task import gate as task_gate
from artagents.core.task.active_run import write_active_run
from artagents.core.task.events import canonical_event_json, read_events
from artagents.core.task.plan import (
    TaskPlanError,
    compute_plan_hash,
    load_plan,
    step_dir_for_path,
)


# Phase 1/2 fixture hash captured before _step_to_dict gained produces/repeat handling.
# DO NOT regenerate; if the canonicalization drifts, fix the canonicalization, not this fixture.
LEGACY_FIXTURE_PLAN: dict = {
    "plan_id": "p1",
    "version": 1,
    "steps": [
        {"id": "s1", "kind": "code", "command": "echo one"},
        {
            "id": "s2",
            "kind": "attested",
            "command": "ack --project demo --step s2",
            "instructions": "review",
            "ack": {"kind": "agent"},
        },
        {
            "id": "s3",
            "kind": "nested",
            "plan": {
                "plan_id": "c",
                "version": 1,
                "steps": [{"id": "c1", "kind": "code", "command": "echo c1"}],
            },
        },
    ],
}
FROZEN_LEGACY_HASH = "sha256:0049398e632120dc7771ce3fe9280c76beff9311dc4920d7d2f6bda711f167ab"


def _setup_run(tmp_projects_root: Path, plan: dict, *, slug: str = "demo", run_id: str = "run-1") -> Path:
    create_project(slug, root=tmp_projects_root)
    plan_path = tmp_projects_root / slug / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    write_active_run(slug, run_id=run_id, plan_hash=compute_plan_hash(plan_path), root=tmp_projects_root)
    return plan_path


def _events_path(tmp_projects_root: Path, slug: str, run_id: str) -> Path:
    return tmp_projects_root / slug / "runs" / run_id / "events.jsonl"


def test_code_produces_check_fails_rewinds_cursor(tmp_projects_root: Path) -> None:
    plan = {
        "plan_id": "p",
        "version": 1,
        "steps": [
            {
                "id": "step-1",
                "kind": "code",
                "command": "echo go",
                "produces": {
                    "out": {
                        "path": "out.json",
                        "check": {"check_id": "json_file", "params": {}, "sentinel": False},
                    }
                },
            }
        ],
    }
    _setup_run(tmp_projects_root, plan)
    events_path = _events_path(tmp_projects_root, "demo", "run-1")

    decision = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert decision.active is True

    # Subprocess writes garbage that fails json_file.
    step_dir = step_dir_for_path("demo", "run-1", ("step-1",), root=tmp_projects_root)
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "out.json").write_text("not json", encoding="utf-8")

    task_gate.record_dispatch_complete(decision, 0)

    kinds = [e["kind"] for e in read_events(events_path)]
    assert kinds == [
        "step_dispatched",
        "step_completed",
        "produces_check_failed",
        "cursor_rewind",
    ]

    # Next gate_command of the same command re-dispatches (cursor still on step-1).
    decision2 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert decision2.active is True
    kinds2 = [e["kind"] for e in read_events(events_path)]
    assert kinds2 == [
        "step_dispatched",
        "step_completed",
        "produces_check_failed",
        "cursor_rewind",
        "step_dispatched",
    ]


def test_code_produces_check_passes_advances(tmp_projects_root: Path) -> None:
    plan = {
        "plan_id": "p",
        "version": 1,
        "steps": [
            {
                "id": "step-1",
                "kind": "code",
                "command": "echo go",
                "produces": {
                    "out": {
                        "path": "out.json",
                        "check": {"check_id": "json_file", "params": {}, "sentinel": False},
                    }
                },
            },
            {"id": "step-2", "kind": "code", "command": "echo two"},
        ],
    }
    _setup_run(tmp_projects_root, plan)
    events_path = _events_path(tmp_projects_root, "demo", "run-1")

    decision = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    step_dir = step_dir_for_path("demo", "run-1", ("step-1",), root=tmp_projects_root)
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "out.json").write_text('{"ok": 1}', encoding="utf-8")
    task_gate.record_dispatch_complete(decision, 0)

    kinds = [e["kind"] for e in read_events(events_path)]
    assert kinds == [
        "step_dispatched",
        "step_completed",
        "produces_check_passed",
    ]

    decision2 = task_gate.gate_command("demo", "echo two", ["echo", "two"], root=tmp_projects_root)
    assert decision2.active is True
    assert decision2.plan_step_id == "step-2"


def test_attested_sentinel_only_check_rejected_at_load(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({
            "plan_id": "p",
            "version": 1,
            "steps": [
                {
                    "id": "s1",
                    "kind": "attested",
                    "command": "ack --project demo --step s1",
                    "instructions": "review",
                    "ack": {"kind": "agent"},
                    "produces": {
                        "out": {
                            "path": "out.bin",
                            "check": {"check_id": "file_nonempty", "params": {}, "sentinel": True},
                        }
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    with pytest.raises(TaskPlanError, match="requires a semantic check"):
        load_plan(plan_path)


def test_attested_with_all_of_semantic_check_accepts(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({
            "plan_id": "p",
            "version": 1,
            "steps": [
                {
                    "id": "s1",
                    "kind": "attested",
                    "command": "ack --project demo --step s1",
                    "instructions": "review",
                    "ack": {"kind": "agent"},
                    "produces": {
                        "out": {
                            "path": "out.json",
                            "check": {
                                "check_id": "all_of",
                                "params": {
                                    "checks": [
                                        {"check_id": "file_nonempty", "params": {}, "sentinel": True},
                                        {"check_id": "json_file", "params": {}, "sentinel": False},
                                    ]
                                },
                                "sentinel": False,
                            },
                        }
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    plan = load_plan(plan_path)
    assert plan.steps[0].produces[0].name == "out"
    assert plan.steps[0].produces[0].check.sentinel is False


def test_code_with_sentinel_only_check_accepts(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({
            "plan_id": "p",
            "version": 1,
            "steps": [
                {
                    "id": "s1",
                    "kind": "code",
                    "command": "echo go",
                    "produces": {
                        "out": {
                            "path": "out.bin",
                            "check": {"check_id": "file_nonempty", "params": {}, "sentinel": True},
                        }
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    plan = load_plan(plan_path)
    assert plan.steps[0].produces[0].check.sentinel is True


def test_legacy_produces_list_normalizes_to_sentinel_dict(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    legacy_dict = {
        "plan_id": "p",
        "version": 1,
        "steps": [
            {
                "id": "s1",
                "kind": "code",
                "command": "echo go",
                "produces": ["a.json", "subdir/b.json"],
            }
        ],
    }
    plan_path.write_text(json.dumps(legacy_dict), encoding="utf-8")
    plan = load_plan(plan_path)
    entries = plan.steps[0].produces
    assert {(e.name, e.path, e.check.check_id, e.check.sentinel) for e in entries} == {
        ("a", "a.json", "file_nonempty", True),
        ("b", "subdir/b.json", "file_nonempty", True),
    }
    # to_dict round-trips canonical (sorted by name).
    out = plan.to_dict()
    produces_out = out["steps"][0]["produces"]
    assert list(produces_out.keys()) == ["a", "b"]
    # Plan-hash is stable across two loads.
    h1 = compute_plan_hash(plan_path)
    h2 = compute_plan_hash(plan_path)
    assert h1 == h2


def test_legacy_no_produces_no_repeat_hash_unchanged(tmp_path: Path) -> None:
    """FLAG-P3-003: pin canonical hash for a legacy Phase 1/2 plan."""
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(LEGACY_FIXTURE_PLAN), encoding="utf-8")
    digest = hashlib.sha256(canonical_event_json(LEGACY_FIXTURE_PLAN).encode("utf-8")).hexdigest()
    fixture_hash_from_payload = f"sha256:{digest}"
    assert fixture_hash_from_payload == FROZEN_LEGACY_HASH
    assert compute_plan_hash(plan_path) == FROZEN_LEGACY_HASH
