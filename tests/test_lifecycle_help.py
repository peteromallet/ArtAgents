"""Lifecycle help should exit cleanly."""

from __future__ import annotations

from astrid.core.task.lifecycle import cmd_next, cmd_start
from astrid.core.task.lifecycle_ack import cmd_ack


def test_lifecycle_help_returns_zero() -> None:
    assert cmd_start(["--help"]) == 0
    assert cmd_next(["--help"]) == 0
    assert cmd_ack(["--help"]) == 0
