"""User-facing thread prefix formatting."""

from __future__ import annotations

import sys
from typing import TextIO

from .attribute import AttributionDecision


def format_prefix_lines(
    decision: AttributionDecision,
    *,
    variants: int | None = None,
    variants_message: str | None = None,
) -> list[str]:
    label = decision.label.strip() or "ArtAgents thread"
    run_part = f"run #{decision.run_number}" if decision.run_number else "run"
    lines = [f"[thread] {label} · {run_part} · {decision.thread_id}"]
    if variants is not None:
        message = variants_message or f"requested {variants}; use `thread keep` after reviewing outputs."
        lines.append(f"[variants] {message}")
    elif variants_message:
        lines.append(f"[variants] {variants_message}")
    if decision.notice:
        lines.append(f"Notice: {decision.notice}")
    return lines


def emit_prefix(lines: list[str], *, stream: TextIO | None = None) -> None:
    if not lines:
        return
    target = stream or sys.stdout
    for line in lines:
        print(line, file=target)
    print(file=target)
