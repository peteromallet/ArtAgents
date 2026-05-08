from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.orchestrator.schema import (
    OrchestratorValidationError,
    validate_orchestrator_definition,
)
from astrid.core.task.plan import (
    AttestedStep,
    CodeStep,
    NestedStep,
    TaskPlanError,
    iter_steps_with_path,
    load_plan,
)


def _write(tmp_path: Path, payload: dict) -> Path:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    return plan_path


def test_legacy_plan_loads_as_single_code_step(tmp_path: Path) -> None:
    plan_path = _write(
        tmp_path,
        {"plan_id": "p1", "version": 1, "steps": [{"id": "s1", "command": "echo one"}]},
    )

    plan = load_plan(plan_path)

    assert len(plan.steps) == 1
    assert isinstance(plan.steps[0], CodeStep)
    assert plan.steps[0].id == "s1"
    assert plan.steps[0].kind == "code"
    assert plan.steps[0].command == "echo one"


def test_legacy_and_canonical_code_step_normalize_to_identical_to_dict(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    canonical_dir = tmp_path / "canonical"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    canonical_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = legacy_dir / "plan.json"
    canonical_path = canonical_dir / "plan.json"
    legacy_path.write_text(
        json.dumps({"plan_id": "p1", "version": 1, "steps": [{"id": "s1", "command": "echo one"}]}),
        encoding="utf-8",
    )
    canonical_path.write_text(
        json.dumps(
            {
                "plan_id": "p1",
                "version": 1,
                "steps": [{"id": "s1", "kind": "code", "command": "echo one"}],
            }
        ),
        encoding="utf-8",
    )

    legacy_plan = load_plan(legacy_path)
    canonical_plan = load_plan(canonical_path)

    assert legacy_plan.to_dict() == canonical_plan.to_dict()
    assert legacy_plan.to_dict()["steps"][0]["kind"] == "code"


def test_code_step_with_orchestrators_run_is_rejected_at_load(tmp_path: Path) -> None:
    plan_path = _write(
        tmp_path,
        {
            "plan_id": "p1",
            "version": 1,
            "steps": [
                {
                    "id": "s1",
                    "kind": "code",
                    "command": "python3 -m astrid orchestrators run hype",
                }
            ],
        },
    )

    with pytest.raises(TaskPlanError) as exc:
        load_plan(plan_path)
    assert "nested" in str(exc.value)


def test_code_step_with_astrid_orchestrators_run_is_rejected(tmp_path: Path) -> None:
    plan_path = _write(
        tmp_path,
        {
            "plan_id": "p1",
            "version": 1,
            "steps": [
                {"id": "s1", "kind": "code", "command": "astrid orchestrators run hype"}
            ],
        },
    )

    with pytest.raises(TaskPlanError) as exc:
        load_plan(plan_path)
    assert "nested" in str(exc.value)


def test_sibling_id_collision_in_one_frame_is_rejected(tmp_path: Path) -> None:
    plan_path = _write(
        tmp_path,
        {
            "plan_id": "p1",
            "version": 1,
            "steps": [
                {"id": "s1", "command": "echo a"},
                {"id": "s1", "command": "echo b"},
            ],
        },
    )

    with pytest.raises(TaskPlanError, match="duplicate step id"):
        load_plan(plan_path)


def test_identical_leaf_ids_in_different_subtrees_are_accepted(tmp_path: Path) -> None:
    plan_path = _write(
        tmp_path,
        {
            "plan_id": "p1",
            "version": 1,
            "steps": [
                {
                    "id": "s1",
                    "kind": "nested",
                    "plan": {
                        "plan_id": "child1",
                        "version": 1,
                        "steps": [{"id": "c1", "command": "echo a"}],
                    },
                },
                {
                    "id": "s2",
                    "kind": "nested",
                    "plan": {
                        "plan_id": "child2",
                        "version": 1,
                        "steps": [{"id": "c1", "command": "echo b"}],
                    },
                },
            ],
        },
    )

    plan = load_plan(plan_path)
    paths = [path for path, _step in iter_steps_with_path(plan)]
    assert ("s1",) in paths
    assert ("s1", "c1") in paths
    assert ("s2", "c1") in paths


def test_attested_step_requires_instructions_and_ack_kind(tmp_path: Path) -> None:
    plan_path = _write(
        tmp_path,
        {
            "plan_id": "p1",
            "version": 1,
            "steps": [
                {
                    "id": "s1",
                    "kind": "attested",
                    "command": "ack --project demo --step s1",
                    "instructions": "Review and approve",
                    "ack": {"kind": "agent"},
                }
            ],
        },
    )

    plan = load_plan(plan_path)
    assert isinstance(plan.steps[0], AttestedStep)
    assert plan.steps[0].instructions == "Review and approve"
    assert plan.steps[0].ack.kind == "agent"


def test_attested_step_rejects_missing_instructions(tmp_path: Path) -> None:
    plan_path = _write(
        tmp_path,
        {
            "plan_id": "p1",
            "version": 1,
            "steps": [
                {
                    "id": "s1",
                    "kind": "attested",
                    "command": "ack --project demo --step s1",
                    "ack": {"kind": "agent"},
                }
            ],
        },
    )

    with pytest.raises(TaskPlanError, match="instructions"):
        load_plan(plan_path)


def test_nested_step_recursively_validates_child_plan(tmp_path: Path) -> None:
    plan_path = _write(
        tmp_path,
        {
            "plan_id": "p1",
            "version": 1,
            "steps": [
                {
                    "id": "s1",
                    "kind": "nested",
                    "plan": {
                        "plan_id": "c",
                        "version": 1,
                        "steps": [{"id": "c1", "command": "echo c1"}],
                    },
                }
            ],
        },
    )

    plan = load_plan(plan_path)
    assert isinstance(plan.steps[0], NestedStep)
    assert plan.steps[0].plan.steps[0].id == "c1"


def test_to_dict_emits_explicit_kind_for_every_step_recursively(tmp_path: Path) -> None:
    plan_path = _write(
        tmp_path,
        {
            "plan_id": "p1",
            "version": 1,
            "steps": [
                {"id": "s1", "command": "echo one"},
                {
                    "id": "s2",
                    "kind": "nested",
                    "plan": {
                        "plan_id": "c",
                        "version": 1,
                        "steps": [
                            {"id": "c1", "command": "echo c1"},
                            {
                                "id": "c2",
                                "kind": "attested",
                                "command": "ack --project demo --step c2",
                                "instructions": "review",
                                "ack": {"kind": "actor"},
                            },
                        ],
                    },
                },
            ],
        },
    )

    out = load_plan(plan_path).to_dict()
    assert out["steps"][0]["kind"] == "code"
    assert out["steps"][1]["kind"] == "nested"
    assert out["steps"][1]["plan"]["steps"][0]["kind"] == "code"
    assert out["steps"][1]["plan"]["steps"][1]["kind"] == "attested"


def test_orchestrator_definition_legacy_python_runtime_validates() -> None:
    raw = {
        "id": "builtin.hype",
        "name": "Hype",
        "kind": "built_in",
        "version": "1.0",
        "runtime": {"kind": "python", "module": "astrid.packs.builtin.hype", "function": "run"},
    }
    orchestrator = validate_orchestrator_definition(raw)
    assert orchestrator.runtime.kind == "python"


def test_orchestrator_definition_legacy_command_runtime_validates() -> None:
    raw = {
        "id": "builtin.hype",
        "name": "Hype",
        "kind": "built_in",
        "version": "1.0",
        "runtime": {"kind": "command", "command": {"argv": ["echo", "ok"]}},
    }
    orchestrator = validate_orchestrator_definition(raw)
    assert orchestrator.runtime.kind == "command"


def test_orchestrator_definition_rejects_code_runtime_kind() -> None:
    raw = {
        "id": "builtin.hype",
        "name": "Hype",
        "kind": "built_in",
        "version": "1.0",
        "runtime": {"kind": "code", "module": "x", "function": "y"},
    }
    with pytest.raises(OrchestratorValidationError, match="runtime.kind"):
        validate_orchestrator_definition(raw)
