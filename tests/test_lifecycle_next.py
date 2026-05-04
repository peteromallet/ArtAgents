"""T13: cmd_next prints PROHIBITION_PREAMBLE byte-for-byte every call (SD-023);
code-step prints `run: <command>`; attested-step prints instructions + ack
template with --agent or --actor based on ack.kind; iter>=2 ledger and
for_each item ledger render correctly.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _lifecycle_fixtures import setup_run  # noqa: E402

from artagents.core.task import write_iteration_feedback
from artagents.core.task.events import (
    append_event,
    make_iteration_failed_event,
)
from artagents.core.task.events import make_iteration_started_event
from artagents.core.task.gate import GateDecision
from artagents.core.task.lifecycle import cmd_next
from artagents.core.task.preamble import PROHIBITION_PREAMBLE


_BODY_CODE = '''from artagents.orchestrate import orchestrator, code
@orchestrator("demo.code")
def main(): return [code("step_a", argv=["echo", "alpha"])]
'''

_BODY_AGENT = '''from artagents.orchestrate import orchestrator, attested
@orchestrator("demo.review_agent")
def main(): return [attested("review", command="review.sh", instructions="please review", ack="agent")]
'''

_BODY_ACTOR = '''from artagents.orchestrate import orchestrator, attested
@orchestrator("demo.review_actor")
def main(): return [attested("review", command="ok.sh", instructions="confirm", ack="actor")]
'''

_BODY_ITER = '''from artagents.orchestrate import orchestrator, attested, repeat_until
@orchestrator("demo.iter")
def main(): return [attested("review", command="r.sh", instructions="ok", ack="actor",
    repeat=repeat_until(condition="user_approves", max_iterations=3, on_exhaust="fail"))]
'''

_BODY_FE = '''from artagents.orchestrate import orchestrator, attested, repeat_for_each
@orchestrator("demo.fe")
def main(): return [attested("review_each", command="r.sh", instructions="check", ack="actor",
    repeat=repeat_for_each(items=["a","b","c"]))]
'''


def _capture_next(packs: Path, projects: Path) -> str:
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        cmd_next(["--project", "p"], projects_root=projects)
    return buf.getvalue()


def test_preamble_byte_identical_across_two_calls(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "code", _BODY_CODE, "demo.code", run_id="r1")
    out1 = _capture_next(packs, projects)
    out2 = _capture_next(packs, projects)
    # SD-023: preamble is verbatim every call so Stop-hook re-injection sees stable bytes.
    assert PROHIBITION_PREAMBLE in out1
    assert PROHIBITION_PREAMBLE in out2
    assert out1 == out2, "cmd_next must produce byte-identical output across calls"


def test_code_step_prints_command(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "code", _BODY_CODE, "demo.code", run_id="r2")
    out = _capture_next(packs, projects)
    assert "run: echo alpha" in out


def test_attested_agent_template(tmp_path: Path) -> None:
    packs, projects = setup_run(
        tmp_path, "demo", "review_agent", _BODY_AGENT, "demo.review_agent", run_id="r3"
    )
    out = _capture_next(packs, projects)
    assert "please review" in out
    assert "--decision approve --agent <id>" in out
    # No --actor token in template since ack.kind=agent
    template_line = next(line for line in out.splitlines() if "artagents ack review" in line)
    assert "--actor" not in template_line


def test_attested_actor_template(tmp_path: Path) -> None:
    packs, projects = setup_run(
        tmp_path, "demo", "review_actor", _BODY_ACTOR, "demo.review_actor", run_id="r4"
    )
    out = _capture_next(packs, projects)
    assert "confirm" in out
    assert "--decision approve --actor <name>" in out


def test_iteration_ledger_at_iter_2(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "iter", _BODY_ITER, "demo.iter", run_id="r5")
    events_path = projects / "p" / "runs" / "r5" / "events.jsonl"
    # Simulate iteration 1 attempted+failed; write iter-1 cumulative feedback.
    append_event(events_path, make_iteration_started_event(("review",), 1))
    decision = GateDecision(
        active=True, run_id="r5", slug="p", project_root=projects / "p",
        plan_step_path=("review",), iteration=1, events_path=events_path,
    )
    write_iteration_feedback(decision, "be more concise")
    append_event(events_path, make_iteration_failed_event(("review",), 1, reason="iterate_feedback"))
    out = _capture_next(packs, projects)
    assert "feedback ledger (through iteration 1)" in out
    assert "be more concise" in out


def test_for_each_item_ledger(tmp_path: Path) -> None:
    packs, projects = setup_run(tmp_path, "demo", "fe", _BODY_FE, "demo.fe", run_id="r6")
    out = _capture_next(packs, projects)
    assert "for_each items" in out
    assert "[ ] a" in out
    assert "[ ] b" in out
    assert "[ ] c" in out
    assert "<- next" in out
    # ack template gets the [--item <id>] hint when host is for_each.
    assert "[--item <id>]" in out
