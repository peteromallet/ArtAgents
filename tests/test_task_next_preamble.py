"""T7 (Phase 6): the no-cursor-move golden run.

Calling `astrid next` repeatedly without an `ack` is intended to be
purely informational: the preamble must be re-injected verbatim on each
call (SD-023), the two outputs must be byte-identical, and the run cursor
(events.jsonl) must NOT advance between calls.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lifecycle_fixtures import setup_run  # noqa: E402

from astrid.core.task.lifecycle import cmd_next
from astrid.core.task.preamble import PROHIBITION_PREAMBLE


_BODY_CODE = '''from astrid.orchestrate import orchestrator, code
@orchestrator("demo.code")
def main(): return [code("step_a", argv=["echo", "alpha"])]
'''


def _capture_next(projects: Path) -> str:
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = cmd_next(["--project", "p"], projects_root=projects)
    assert rc == 0, f"cmd_next returned non-zero rc={rc}; stderr={err.getvalue()!r}"
    return buf.getvalue()


def test_next_is_idempotent_and_re_injects_preamble(tmp_path: Path) -> None:
    packs, projects = setup_run(
        tmp_path, "demo", "code", _BODY_CODE, "demo.code", run_id="r1"
    )
    events_path = projects / "p" / "runs" / "r1" / "events.jsonl"

    bytes_before = events_path.read_bytes()

    out1 = _capture_next(projects)
    bytes_after_first = events_path.read_bytes()

    out2 = _capture_next(projects)
    bytes_after_second = events_path.read_bytes()

    # (a) Preamble verbatim in BOTH outputs (SD-023 re-injection contract).
    assert PROHIBITION_PREAMBLE in out1
    assert PROHIBITION_PREAMBLE in out2

    # (b) Byte-identical outputs across calls — Stop-hook re-injection sees
    # stable bytes regardless of how many times Claude triggers it.
    assert out1 == out2, "cmd_next must produce byte-identical output across calls"

    # (c) No-cursor-move golden run: events.jsonl is unchanged after either
    # call. `next` is informational; only `ack` advances the cursor.
    assert bytes_after_first == bytes_before, (
        "cmd_next must not write to events.jsonl on first call"
    )
    assert bytes_after_second == bytes_before, (
        "cmd_next must not write to events.jsonl on second call"
    )
