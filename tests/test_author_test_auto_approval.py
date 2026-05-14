"""Phase 9 author-test auto-approval mode (FLAG-P9-001 + FLAG-P9-002).

Behavior under test:
  * cmd_start succeeds with ASTRID_AUTHOR_TEST=1 (FLAG-P9-001 — no guard).
  * Without ASTRID_AUTHOR_TEST, an ack with --actor mismatching
    ASTRID_ACTOR is rejected (existing self-ack-prep guard fires).
  * With ASTRID_AUTHOR_TEST=1, the same mismatched ack succeeds. The
    resulting step_attested event keeps the canonical attestor_kind='actor'
    (NOT 'author_test' — FLAG-P9-002) and gains source='author_test' on the
    way through _dispatch_attested.

Run state is seeded via cmd_start (FLAG-P9-004); we never write
active_run.json/plan.json by hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from astrid.core.task.env import ASTRID_ACTOR, ASTRID_AUTHOR_TEST
from astrid.core.task.events import read_events
from astrid.core.task.lifecycle import cmd_start
from astrid.core.task.lifecycle_ack import cmd_ack


_DEMO_PACK_BODY = '''from astrid.orchestrate import attested, orchestrator


@orchestrator("demo.app")
def app():
    return [
        attested(
            "review",
            command="review",
            instructions="approve",
            ack="actor",
        ),
    ]
'''


def _make_demo_pack(tmp_path: Path) -> Path:
    packs = tmp_path / "packs"
    pack = packs / "demo"
    pack.mkdir(parents=True)
    (pack / "app.py").write_text(_DEMO_PACK_BODY, encoding="utf-8")
    return packs


def test_author_test_env_var_unlocks_attested_auto_approval(
    tmp_path: Path,
    tmp_projects_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packs = _make_demo_pack(tmp_path)
    slug = "auto_approval_demo"

    # FLAG-P9-001: cmd_start must succeed even when ASTRID_AUTHOR_TEST=1.
    # Compile the demo pack first (cmd_start expects build/<orch>.json).
    from astrid.orchestrate.compile import compile_to_path
    compile_to_path("demo.app", packs_root=packs)

    monkeypatch.setenv(ASTRID_ACTOR, "alice")
    monkeypatch.setenv(ASTRID_AUTHOR_TEST, "1")
    rc_start = cmd_start(
        ["demo.app", "--project", slug, "--name", "r1"],
        packs_root=packs,
        projects_root=tmp_projects_root,
    )
    assert rc_start == 0, "cmd_start must not gate on ASTRID_AUTHOR_TEST (FLAG-P9-001)"

    # Without ASTRID_AUTHOR_TEST, --actor mismatch must be rejected.
    monkeypatch.delenv(ASTRID_AUTHOR_TEST, raising=False)
    rc_reject = cmd_ack(
        [
            "review",
            "--project",
            slug,
            "--decision",
            "approve",
            "--actor",
            "mallory",
        ],
        projects_root=tmp_projects_root,
    )
    assert rc_reject != 0, "actor mismatch must be rejected without ASTRID_AUTHOR_TEST"

    events_path = tmp_projects_root / slug / "runs" / "r1" / "events.jsonl"
    events_before = read_events(events_path)
    assert not any(
        ev.get("kind") == "step_attested" for ev in events_before
    ), "rejected ack must not write step_attested"

    # With ASTRID_AUTHOR_TEST=1, the same mismatched --actor is accepted.
    monkeypatch.setenv(ASTRID_AUTHOR_TEST, "1")
    rc_accept = cmd_ack(
        [
            "review",
            "--project",
            slug,
            "--decision",
            "approve",
            "--actor",
            "mallory",
        ],
        projects_root=tmp_projects_root,
    )
    assert rc_accept == 0, "actor mismatch must be accepted with ASTRID_AUTHOR_TEST=1"

    events = read_events(events_path)
    last = events[-1]
    assert last["kind"] == "step_attested"
    # FLAG-P9-002: kind enum stays canonical ('actor'), NOT 'author_test'.
    assert last["attestor_kind"] == "actor"
    assert last["attestor_id"] == "mallory"
    # Provenance rides on a separate event['source'] field.
    assert last["source"] == "author_test"
