"""T6 (Phase 6): snapshot test for the SD-023 prohibition preamble.

Pins the exact byte content of PROHIBITION_PREAMBLE so any silent edit to
the constant fails this test. The preamble is part of the documented Claude
Code Stop-hook contract; if the wording changes, that's a deliberate update
and this snapshot must be updated alongside it.
"""

from __future__ import annotations

from artagents.core.task.preamble import PROHIBITION_PREAMBLE


_EXPECTED_PREAMBLE = (
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


def test_preamble_is_non_empty_str() -> None:
    assert isinstance(PROHIBITION_PREAMBLE, str)
    assert PROHIBITION_PREAMBLE != ""


def test_preamble_byte_snapshot() -> None:
    assert PROHIBITION_PREAMBLE == _EXPECTED_PREAMBLE
    assert PROHIBITION_PREAMBLE.encode("utf-8") == _EXPECTED_PREAMBLE.encode("utf-8")
