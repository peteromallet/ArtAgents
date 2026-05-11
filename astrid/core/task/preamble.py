"""Prohibition preamble re-injected into every ``astrid next`` invocation.

Phase 5 ships only the constant; Phase 6 will wire a Stop-hook handler that
re-prints it so context decay does not erode the rules over a long run. Do
not import this into hook config from Phase 5.

SD-023 (amended Sprint 1): PROHIBITION_PREAMBLE precedes every
operator-facing message WITHIN A BOUND SESSION. The 'no session bound'
error printed by the CLI gate (astrid/pipeline.py) is the documented
exception — preamble would be premature for an agent not yet in task
mode.
"""

from __future__ import annotations

PROHIBITION_PREAMBLE = (
    "ARTAGENTS TASK RUN — PROHIBITIONS\n"
    "- You are inside a frozen plan. Plan structure is pinned by hash; deviation "
    "from the printed step is rejected at the gate.\n"
    "- Do not edit plan.json or events.jsonl by hand. Both are append-only / "
    "immutable; tampering breaks the hash chain and aborts the run.\n"
    "- Advance only via `astrid ack` or by running the printed argv. No "
    "freelancing, no parallel commands, no re-ordering steps.\n"
    "- Use `astrid abort --project <slug>` to leave the run cleanly. Do not "
    "delete active_run.json or run directories to escape."
)


__all__ = ["PROHIBITION_PREAMBLE"]
