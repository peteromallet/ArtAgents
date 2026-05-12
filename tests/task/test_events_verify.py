"""Sprint 5b: hash-chain verification tests (T5 / T12).

Tests ``verify_chain`` against synthesised event logs: known-good,
hand-corrupted hash, broken prev_hash chain, and --strict mode.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.task.events import (
    ZERO_HASH,
    _event_hash,
    canonical_event_json,
    verify_chain,
)
from astrid.core.task.plan import load_plan

# ── Helpers for synthetic events ────────────────────────────────────────


def _make_event(fields: dict, prev_hash: str) -> dict:
    """Build an event dict with a correct ``hash`` field."""
    ev = dict(fields)
    ev["hash"] = _event_hash(prev_hash, ev)
    return ev


def _build_chain(events: list[dict]) -> list[dict]:
    """Given events without hashes, compute the chain and return with hashes."""
    chain: list[dict] = []
    prev = ZERO_HASH
    for raw in events:
        ev = dict(raw)
        ev["hash"] = _event_hash(prev, ev)
        chain.append(ev)
        prev = ev["hash"]
    return chain


def _write_events(path: Path, events: list[dict]) -> None:
    """Write events to a JSONL file."""
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, sort_keys=True, separators=(",", ":")) + "\n")


# ── Known-good chain passes ─────────────────────────────────────────────


def test_clean_chain_passes(tmp_path: Path) -> None:
    """A synthetically correct hash chain passes ``verify_chain``."""
    raw_events = [
        {"kind": "run_started", "run_id": "r1", "plan_hash": "sha256:abc", "ts": "2026-01-01T00:00:00Z"},
        {"kind": "step_dispatched", "plan_step_path": ["s1"], "ts": "2026-01-01T00:00:01Z"},
        {"kind": "step_completed", "plan_step_path": ["s1"], "returncode": 0, "ts": "2026-01-01T00:00:02Z"},
        {"kind": "run_completed", "ts": "2026-01-01T00:00:03Z"},
    ]
    chain = _build_chain(raw_events)
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, chain)

    ok, line_idx, err_msg = verify_chain(events_path)
    assert ok is True
    assert err_msg is None
    assert line_idx == 3  # zero-indexed, 4 events → last is index 3


def test_empty_events_file_passes(tmp_path: Path) -> None:
    """An empty events.jsonl is trivially valid."""
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("", encoding="utf-8")
    ok, line_idx, err_msg = verify_chain(events_path)
    assert ok is True
    assert line_idx == -1


# ── Corrupted chain caught ──────────────────────────────────────────────


def test_tampered_hash_caught(tmp_path: Path) -> None:
    """If a line's hash does not match the recomputed hash, verify_chain fails."""
    raw_events = [
        {"kind": "run_started", "run_id": "r1", "plan_hash": "sha256:abc", "ts": "2026-01-01T00:00:00Z"},
        {"kind": "step_completed", "plan_step_path": ["s1"], "returncode": 0, "ts": "2026-01-01T00:00:01Z"},
    ]
    chain = _build_chain(raw_events)

    # Tamper: change the kind of line 2 but keep its old hash
    chain[1] = dict(chain[1], kind="step_failed")

    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, chain)

    ok, line_idx, err_msg = verify_chain(events_path)
    assert ok is False
    assert line_idx == 1  # zero-indexed line 1 (second event)
    assert err_msg is not None
    assert "hash mismatch" in (err_msg or "").lower() or f"line {line_idx + 1}" in (err_msg or "")


def test_broken_prev_hash_caught(tmp_path: Path) -> None:
    """If prev_hash link is broken, verify_chain catches it at the affected line."""
    raw_events = [
        {"kind": "run_started", "run_id": "r1", "plan_hash": "sha256:abc", "ts": "2026-01-01T00:00:00Z"},
        {"kind": "step_dispatched", "plan_step_path": ["s1"], "ts": "2026-01-01T00:00:01Z"},
        {"kind": "step_completed", "plan_step_path": ["s1"], "returncode": 0, "ts": "2026-01-01T00:00:02Z"},
    ]
    chain = _build_chain(raw_events)

    # Corrupt: swap event 2 (index 1) hash with something bogus
    chain[1] = dict(chain[1], hash="sha256:" + "ff" * 64)

    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, chain)

    ok, line_idx, err_msg = verify_chain(events_path)
    assert ok is False
    # The mismatch should be at line 1 (the corrupted event)
    assert err_msg is not None and ("hash" in err_msg.lower() or "broken" in err_msg.lower())


def test_invalid_json_caught(tmp_path: Path) -> None:
    """Garbage on a line is caught with a descriptive error."""
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("this is not json\n", encoding="utf-8")

    ok, line_idx, err_msg = verify_chain(events_path)
    assert ok is False
    assert line_idx == 0
    assert err_msg is not None and "json" in err_msg.lower()


def test_missing_hash_field_caught(tmp_path: Path) -> None:
    """A valid JSON line without a hash field fails."""
    events_path = tmp_path / "events.jsonl"
    events_path.write_text('{"kind":"run_started"}\n', encoding="utf-8")

    ok, line_idx, err_msg = verify_chain(events_path)
    assert ok is False
    assert err_msg is not None and "hash" in err_msg.lower()


# ── --strict mode: validate mutations ───────────────────────────────────


def test_strict_mode_with_clean_plan(
    tmp_path: Path, tmp_projects_root: Path
) -> None:
    """``--strict`` replays plan_mutated events through the validator.

    Constructs a minimal project with a valid v2 plan and a run with
    a plan_mutated event whose diff passes the six-invariant check.
    """
    from astrid.core.project.project import create_project
    from astrid.core.task.active_run import write_active_run

    slug = "strict-test"
    run_id = "run-strict"
    create_project(slug, root=tmp_projects_root)
    proj_root = tmp_projects_root / slug
    runs_dir = proj_root / "runs"
    runs_dir.mkdir(exist_ok=True)
    run_root = runs_dir / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    # v2 plan with two steps
    plan_payload = {
        "plan_id": "p-strict",
        "version": 2,
        "steps": [
            {
                "id": "s1",
                "kind": "code",
                "adapter": "local",
                "command": "echo one",
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
            {
                "id": "s2",
                "kind": "code",
                "adapter": "local",
                "command": "echo two",
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
        ],
    }
    plan_path = proj_root / "plan.json"
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")

    from astrid.core.task.plan import compute_plan_hash
    plan_hash = compute_plan_hash(plan_path)

    # Load the plan to get canonical step dicts for the diff
    plan = load_plan(plan_path)

    # Build a synthetic plan_mutated event (add-step after s1)
    raw_events = [
        {
            "kind": "run_started",
            "run_id": run_id,
            "plan_hash": plan_hash,
            "ts": "2026-01-01T00:00:00Z",
        },
        {
            "kind": "plan_mutated",
            "run_id": run_id,
            "diff": {
                "op": "add",
                "after": "s1",
                "step": {
                    "id": "s3",
                    "kind": "code",
                    "adapter": "local",
                    "command": "echo three",
                    "cost": {"amount": 0, "currency": "USD", "source": "local"},
                },
            },
            "ts": "2026-01-01T00:00:01Z",
        },
        {"kind": "run_completed", "ts": "2026-01-01T00:00:02Z"},
    ]
    chain = _build_chain(raw_events)
    events_path = run_root / "events.jsonl"
    _write_events(events_path, chain)

    write_active_run(slug, run_id=run_id, plan_hash=plan_hash, root=tmp_projects_root)

    # Invoke cmd_events_verify with --strict
    from astrid.core.task.run_audit import cmd_events_verify

    rc = cmd_events_verify(
        ["--run", run_id, "--project", slug, "--strict"],
        projects_root=tmp_projects_root,
    )
    assert rc == 0


def test_strict_mode_with_invalid_mutation(
    tmp_path: Path, tmp_projects_root: Path
) -> None:
    """``--strict`` catches a mutation that violates invariants."""
    from astrid.core.project.project import create_project
    from astrid.core.task.active_run import write_active_run

    slug = "strict-bad"
    run_id = "run-bad"
    create_project(slug, root=tmp_projects_root)
    proj_root = tmp_projects_root / slug
    runs_dir = proj_root / "runs"
    runs_dir.mkdir(exist_ok=True)
    run_root = runs_dir / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    plan_payload = {
        "plan_id": "p-bad",
        "version": 2,
        "steps": [
            {
                "id": "s1",
                "kind": "code",
                "adapter": "local",
                "command": "echo one",
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
        ],
    }
    plan_path = proj_root / "plan.json"
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")

    from astrid.core.task.plan import compute_plan_hash
    plan_hash = compute_plan_hash(plan_path)

    # Add a step with a duplicate id (I1 violation)
    raw_events = [
        {
            "kind": "run_started",
            "run_id": run_id,
            "plan_hash": plan_hash,
            "ts": "2026-01-01T00:00:00Z",
        },
        {
            "kind": "plan_mutated",
            "run_id": run_id,
            "diff": {
                "op": "add",
                "after": "s1",
                "step": {
                    "id": "s1",  # duplicate — should fail I1
                    "kind": "code",
                    "adapter": "local",
                    "command": "echo duplicate",
                    "cost": {"amount": 0, "currency": "USD", "source": "local"},
                },
            },
            "ts": "2026-01-01T00:00:01Z",
        },
        {"kind": "run_completed", "ts": "2026-01-01T00:00:02Z"},
    ]
    chain = _build_chain(raw_events)
    events_path = run_root / "events.jsonl"
    _write_events(events_path, chain)

    write_active_run(slug, run_id=run_id, plan_hash=plan_hash, root=tmp_projects_root)

    from astrid.core.task.run_audit import cmd_events_verify

    rc = cmd_events_verify(
        ["--run", run_id, "--project", slug, "--strict"],
        projects_root=tmp_projects_root,
    )
    # Should return non-zero because strict validation catches the duplicate
    assert rc != 0