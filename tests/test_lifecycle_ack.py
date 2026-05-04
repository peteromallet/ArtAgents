"""T14: cmd_ack scenarios (a)-(m) covering FLAG-P5-001 + FLAG-P5-002 +
identity matrix + retry/iterate gating + cumulative feedback + abort delegation.
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _lifecycle_fixtures import setup_run  # noqa: E402

from artagents.core.task.active_run import read_active_run
from artagents.core.task.events import (
    append_event,
    make_produces_check_failed_event,
    make_step_attested_event,
)
from artagents.core.task.lifecycle import cmd_ack


_ATTESTED_REVIEW = '''from artagents.orchestrate import orchestrator, attested
@orchestrator("demo.review")
def main(): return [attested("review", command="review.sh", instructions="please review", ack="actor")]
'''

_ATTESTED_PRODUCES = '''from artagents.orchestrate import orchestrator, attested
from artagents.verify import json_file
@orchestrator("demo.with_produces")
def main(): return [attested("review", command="review.sh", instructions="check", ack="actor", produces={"out": json_file()})]
'''

_ITER = '''from artagents.orchestrate import orchestrator, attested, repeat_until
@orchestrator("demo.iter")
def main(): return [attested("review", command="r.sh", instructions="ok", ack="actor",
    repeat=repeat_until(condition="user_approves", max_iterations=3, on_exhaust="fail"))]
'''

_NON_USER_APPROVES = '''from artagents.orchestrate import orchestrator, attested, repeat_until
@orchestrator("demo.va")
def main(): return [attested("review", command="r.sh", instructions="ok", ack="actor",
    repeat=repeat_until(condition="verifier_passes", max_iterations=3, on_exhaust="fail"))]
'''

_CODE = '''from artagents.orchestrate import orchestrator, code
@orchestrator("demo.code")
def main(): return [code("step_a", argv=["echo","x"])]
'''


def _ack(packs: Path, projects: Path, *args: str) -> tuple[int, str, str]:
    buf, err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = cmd_ack(list(args), projects_root=projects)
    return rc, buf.getvalue(), err.getvalue()


def test_a_approve_attested_review_sh_writes_step_attested(tmp_path: Path) -> None:
    """FLAG-P5-001 regression: command='review.sh' (NOT 'ack --step ...')."""
    packs, projects = setup_run(
        tmp_path, "demo", "review", _ATTESTED_REVIEW, "demo.review", run_id="ra",
        start_actor="bob",
    )
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc, out, err = _ack(packs, projects, "review", "--project", "p", "--decision", "approve", "--actor", "alice")
    assert rc == 0, f"out={out!r} err={err!r}"
    events = [json.loads(line) for line in (projects/"p"/"runs"/"ra"/"events.jsonl").read_text().splitlines()]
    assert any(e["kind"] == "step_attested" and e["plan_step_id"] == "review" for e in events)


def test_b_approve_missing_identity_rejected(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "review", _ATTESTED_REVIEW, "demo.review", run_id="rb")
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc, _, _ = _ack(packs, projects, "review", "--project", "p", "--decision", "approve")
    assert rc != 0


def test_c_approve_both_flags_argparse_rejects(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "review", _ATTESTED_REVIEW, "demo.review", run_id="rc")
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc, _, _ = _ack(
        packs, projects, "review", "--project", "p", "--decision", "approve",
        "--agent", "ag1", "--actor", "alice",
    )
    assert rc != 0


def test_d_approve_actor_not_matching_artagents_actor_rejected(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "review", _ATTESTED_REVIEW, "demo.review", run_id="rd")
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc, _, err = _ack(packs, projects, "review", "--project", "p", "--decision", "approve", "--actor", "carol")
    assert rc != 0
    assert "ARTAGENTS_ACTOR" in err


def test_e_self_ack_rejected(tmp_path: Path) -> None:
    """run_started.actor == --actor == ARTAGENTS_ACTOR triggers self-ack rejection."""
    packs, projects = setup_run(
        tmp_path, "demo", "review", _ATTESTED_REVIEW, "demo.review", run_id="re",
        start_actor="alice",
    )
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc, _, err = _ack(packs, projects, "review", "--project", "p", "--decision", "approve", "--actor", "alice")
    assert rc != 0
    assert "self-ack" in err


def test_f_retry_without_identity_rejected(tmp_path: Path) -> None:
    """FLAG-P5-002: retry must call validate_attested_identity BEFORE event mutation."""
    packs, projects = setup_run(tmp_path, "demo", "review", _ATTESTED_REVIEW, "demo.review", run_id="rf")
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc, _, _ = _ack(packs, projects, "review", "--project", "p", "--decision", "retry")
    assert rc != 0


def test_g_retry_without_prior_verifier_failure_rejected(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "review", _ATTESTED_REVIEW, "demo.review", run_id="rg")
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc, _, err = _ack(packs, projects, "review", "--project", "p", "--decision", "retry", "--actor", "alice")
    assert rc != 0
    assert "produces_check_failed" in err


def test_h_retry_after_produces_check_failed_appends_cursor_rewind(tmp_path: Path) -> None:
    packs, projects = setup_run(
        tmp_path, "demo", "with_produces", _ATTESTED_PRODUCES, "demo.with_produces", run_id="rh"
    )
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    events_path = projects / "p" / "runs" / "rh" / "events.jsonl"
    append_event(events_path, make_step_attested_event("review", "actor", "alice", ()))
    append_event(
        events_path,
        make_produces_check_failed_event(("review",), "out", check_id="json_file:v1", reason="missing"),
    )
    rc, _, _ = _ack(packs, projects, "review", "--project", "p", "--decision", "retry", "--actor", "alice")
    assert rc == 0
    last = json.loads(events_path.read_text().splitlines()[-1])
    assert last["kind"] == "cursor_rewind"
    assert last["reason"] == "ack retry"


def test_i_iterate_without_identity_rejected(tmp_path: Path) -> None:
    """FLAG-P5-002: iterate must call validate_attested_identity BEFORE event mutation."""
    packs, projects = setup_run(tmp_path, "demo", "iter", _ITER, "demo.iter", run_id="ri")
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc, _, _ = _ack(packs, projects, "review", "--project", "p", "--decision", "iterate", "--feedback", "x")
    assert rc != 0


def test_j_iterate_non_user_approves_rejected(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "va", _NON_USER_APPROVES, "demo.va", run_id="rj")
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc, _, err = _ack(
        packs, projects, "review", "--project", "p", "--decision", "iterate",
        "--actor", "alice", "--feedback", "x",
    )
    assert rc != 0
    assert "verifier_passes" in err


def test_k_iterate_cumulative_feedback(tmp_path: Path) -> None:
    """Two iterate calls produce cumulative feedback.json at iterations/002/."""
    packs, projects = setup_run(tmp_path, "demo", "iter", _ITER, "demo.iter", run_id="rk")
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc1, _, _ = _ack(
        packs, projects, "review", "--project", "p", "--decision", "iterate",
        "--actor", "alice", "--feedback", "less verbose",
    )
    assert rc1 == 0
    rc2, _, _ = _ack(
        packs, projects, "review", "--project", "p", "--decision", "iterate",
        "--actor", "alice", "--feedback", "even shorter",
    )
    assert rc2 == 0
    fb2 = projects / "p" / "runs" / "rk" / "steps" / "review" / "iterations" / "002" / "feedback.json"
    assert fb2.is_file()
    assert json.loads(fb2.read_text()) == ["less verbose", "even shorter"]
    events = [json.loads(line) for line in (projects/"p"/"runs"/"rk"/"events.jsonl").read_text().splitlines()]
    iter_failed = [e for e in events if e.get("kind") == "iteration_failed"]
    assert len(iter_failed) == 2


def test_l_approve_on_code_step_rejected(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "code", _CODE, "demo.code", run_id="rl")
    os.environ["ARTAGENTS_ACTOR"] = "alice"
    rc, _, err = _ack(packs, projects, "step_a", "--project", "p", "--decision", "approve", "--actor", "alice")
    assert rc != 0
    assert "code steps advance via subprocess" in err


def test_m_abort_decision_delegates_without_identity(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "review", _ATTESTED_REVIEW, "demo.review", run_id="rm")
    rc, _, _ = _ack(packs, projects, "review", "--project", "p", "--decision", "abort")
    assert rc == 0
    assert read_active_run("p", root=projects) is None
    events = [json.loads(line) for line in (projects/"p"/"runs"/"rm"/"events.jsonl").read_text().splitlines()]
    assert events[-1]["kind"] == "run_aborted"
