"""Prohibition preamble re-injected into every ``artagents next`` invocation.

Phase 5 ships only the constant; Phase 6 will wire a Stop-hook handler that
re-prints it so context decay does not erode the rules over a long run. Do
not import this into hook config from Phase 5.
"""

from __future__ import annotations

PROHIBITION_PREAMBLE = (
    "ARTAGENTS TASK RUN — PROHIBITIONS\n"
    "- You are inside a frozen plan. Plan structure is pinned by hash; deviation "
    "from the printed step is rejected at the gate.\n"
    "- Do not edit plan.json or events.jsonl by hand. Both are append-only / "
    "immutable; tampering breaks the hash chain and aborts the run.\n"
    "- Advance only via `artagents ack` or by running the printed argv. No "
    "freelancing, no parallel commands, no re-ordering steps.\n"
    "- Use `artagents abort --project <slug>` to leave the run cleanly. Do not "
    "delete active_run.json or run directories to escape."
)


__all__ = ["PROHIBITION_PREAMBLE"]
