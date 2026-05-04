from __future__ import annotations

import json
from pathlib import Path

import pytest

from artagents.core.project.project import create_project
from artagents.core.task.active_run import write_active_run
from artagents.core.task.env import ARTAGENTS_ACTOR
from artagents.core.task.events import (
    append_event,
    make_run_started_event,
    read_events,
    verify_chain,
)
from artagents.core.task.gate import (
    AttestedArgs,
    TaskRunGateError,
    gate_command,
    match_attested_command,
)
from artagents.core.task.plan import compute_plan_hash


_ATTESTED_COMMAND = "ack --project demo --step s1"


def _activate_attested_plan(
    tmp_projects_root: Path,
    *,
    ack_kind: str = "agent",
    actor_at_start: str | None = None,
) -> Path:
    create_project("demo", root=tmp_projects_root)
    plan_path = tmp_projects_root / "demo" / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "plan_id": "p1",
                "version": 1,
                "steps": [
                    {
                        "id": "s1",
                        "kind": "attested",
                        "command": _ATTESTED_COMMAND,
                        "instructions": "Review and approve",
                        "ack": {"kind": ack_kind},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    plan_hash = compute_plan_hash(plan_path)
    write_active_run("demo", run_id="run-1", plan_hash=plan_hash, root=tmp_projects_root)
    events_path = tmp_projects_root / "demo" / "runs" / "run-1" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    append_event(events_path, make_run_started_event("run-1", plan_hash, actor=actor_at_start))
    return events_path


def test_match_attested_command_strips_identity_and_evidence_flags() -> None:
    matched, args = match_attested_command(
        f"{_ATTESTED_COMMAND} --agent claude --evidence a.json --evidence b.json",
        _ATTESTED_COMMAND,
    )
    assert matched is True
    assert args == AttestedArgs(agent="claude", actor=None, evidence=("a.json", "b.json"))


def test_match_attested_command_returns_unmatched_when_remainder_differs() -> None:
    matched, _args = match_attested_command(
        "ack --project other --step s1 --agent claude", _ATTESTED_COMMAND
    )
    assert matched is False


def test_attested_rejects_when_neither_agent_nor_actor(tmp_projects_root: Path) -> None:
    _activate_attested_plan(tmp_projects_root, ack_kind="agent")
    with pytest.raises(TaskRunGateError) as exc:
        gate_command("demo", _ATTESTED_COMMAND, [], root=tmp_projects_root)
    assert "--agent" in exc.value.reason or "--actor" in exc.value.reason
    assert exc.value.recovery == "artagents next --project demo"


def test_attested_rejects_when_both_agent_and_actor(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _activate_attested_plan(tmp_projects_root, ack_kind="agent")
    monkeypatch.setenv(ARTAGENTS_ACTOR, "alice")
    with pytest.raises(TaskRunGateError) as exc:
        gate_command(
            "demo",
            f"{_ATTESTED_COMMAND} --agent claude --actor alice",
            [],
            root=tmp_projects_root,
        )
    assert exc.value.recovery == "artagents next --project demo"


def test_attested_kind_mismatch_agent_step_with_actor_only_rejects(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _activate_attested_plan(tmp_projects_root, ack_kind="agent")
    monkeypatch.setenv(ARTAGENTS_ACTOR, "alice")
    with pytest.raises(TaskRunGateError) as exc:
        gate_command(
            "demo", f"{_ATTESTED_COMMAND} --actor alice", [], root=tmp_projects_root
        )
    assert exc.value.recovery == "artagents next --project demo"


def test_attested_kind_mismatch_actor_step_with_agent_only_rejects(
    tmp_projects_root: Path,
) -> None:
    _activate_attested_plan(tmp_projects_root, ack_kind="actor")
    with pytest.raises(TaskRunGateError) as exc:
        gate_command(
            "demo", f"{_ATTESTED_COMMAND} --agent claude", [], root=tmp_projects_root
        )
    assert exc.value.recovery == "artagents next --project demo"


def test_attested_agent_success_emits_step_attested_with_path_qualified_id(
    tmp_projects_root: Path,
) -> None:
    events_path = _activate_attested_plan(tmp_projects_root, ack_kind="agent")
    decision = gate_command(
        "demo", f"{_ATTESTED_COMMAND} --agent claude", [], root=tmp_projects_root
    )

    assert decision.active is True
    assert decision.step_kind == "attested"
    assert decision.plan_step_id == "s1"

    events = read_events(events_path)
    attested_events = [e for e in events if e["kind"] == "step_attested"]
    assert len(attested_events) == 1
    ev = attested_events[0]
    assert ev["plan_step_id"] == "s1"
    assert ev["attestor_kind"] == "agent"
    assert ev["attestor_id"] == "claude"
    assert ev["evidence"] == []
    assert verify_chain(events_path)[0] is True


def test_attested_actor_success_requires_matching_env(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events_path = _activate_attested_plan(tmp_projects_root, ack_kind="actor")
    monkeypatch.setenv(ARTAGENTS_ACTOR, "alice")
    decision = gate_command(
        "demo", f"{_ATTESTED_COMMAND} --actor alice", [], root=tmp_projects_root
    )

    assert decision.step_kind == "attested"
    events = read_events(events_path)
    attested = next(e for e in events if e["kind"] == "step_attested")
    assert attested["attestor_kind"] == "actor"
    assert attested["attestor_id"] == "alice"


def test_attested_actor_env_mismatch_rejects(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _activate_attested_plan(tmp_projects_root, ack_kind="actor")
    monkeypatch.setenv(ARTAGENTS_ACTOR, "bob")
    with pytest.raises(TaskRunGateError) as exc:
        gate_command(
            "demo", f"{_ATTESTED_COMMAND} --actor alice", [], root=tmp_projects_root
        )
    assert exc.value.recovery == "artagents next --project demo"


def test_attested_self_ack_rejected_when_run_started_actor_matches(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _activate_attested_plan(tmp_projects_root, ack_kind="actor", actor_at_start="alice")
    monkeypatch.setenv(ARTAGENTS_ACTOR, "alice")
    with pytest.raises(TaskRunGateError) as exc:
        gate_command(
            "demo", f"{_ATTESTED_COMMAND} --actor alice", [], root=tmp_projects_root
        )
    assert "self-ack" in exc.value.reason
    assert exc.value.recovery == "artagents next --project demo"


def test_attested_evidence_flags_recorded_and_canonical_match_succeeds(
    tmp_projects_root: Path,
) -> None:
    events_path = _activate_attested_plan(tmp_projects_root, ack_kind="agent")
    decision = gate_command(
        "demo",
        f"{_ATTESTED_COMMAND} --agent claude --evidence a.json --evidence b.json",
        [],
        root=tmp_projects_root,
    )
    assert decision.step_kind == "attested"
    events = read_events(events_path)
    attested = next(e for e in events if e["kind"] == "step_attested")
    assert attested["evidence"] == ["a.json", "b.json"]
    assert verify_chain(events_path)[0] is True


def test_attested_event_advances_cursor_no_double_emission(
    tmp_projects_root: Path,
) -> None:
    """FLAG-007: step_attested advances the cursor inline; record_dispatch_complete
    must NOT emit a companion step_completed event for attested steps."""
    from artagents.core.task.gate import record_dispatch_complete

    events_path = _activate_attested_plan(tmp_projects_root, ack_kind="agent")
    decision = gate_command(
        "demo", f"{_ATTESTED_COMMAND} --agent claude", [], root=tmp_projects_root
    )
    record_dispatch_complete(decision, 0)  # no-op for attested

    events = read_events(events_path)
    kinds = [e["kind"] for e in events]
    assert kinds.count("step_attested") == 1
    assert kinds.count("step_completed") == 0
