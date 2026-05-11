"""Two-tab adversarial test harness for racing subprocess invocations."""

from __future__ import annotations

import multiprocessing
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class RaceResult:
    """Outcome of a two-tab race."""

    p1_pid: int
    p2_pid: int
    p1_exit_code: int
    p2_exit_code: int
    p1_stdout: str
    p1_stderr: str
    p2_stdout: str
    p2_stderr: str
    final_disk_state: dict[str, str] = field(default_factory=dict)

    @property
    def winner_count(self) -> int:
        """Number of processes that exited with code 0."""
        count = 0
        if self.p1_exit_code == 0:
            count += 1
        if self.p2_exit_code == 0:
            count += 1
        return count


def _run_and_capture(
    barrier: multiprocessing.Barrier,
    output_queue: multiprocessing.Queue,
    command: list[str],
    env: dict[str, str] | None,
) -> None:
    """Barrier-synchronized subprocess runner (runs in a child process)."""
    barrier.wait()  # synchronize start
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    output_queue.put(
        {
            "pid": completed.pid if hasattr(completed, "pid") else None,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    )


def _snapshot_disk_state(run_dir: Path) -> dict[str, str]:
    """Capture current on-disk contents of the run directory."""
    state: dict[str, str] = {}
    if run_dir.is_dir():
        for file_path in sorted(run_dir.rglob("*")):
            if file_path.is_file():
                try:
                    state[str(file_path)] = file_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    state[str(file_path)] = "<binary or unreadable>"
    return state


def race_two_tabs(
    setup_fn: Callable[[], Path],
    contended_command: list[str],
    *,
    expected_winner_count: int = 1,
    timeout_seconds: float = 10.0,
) -> RaceResult:
    """Race two subprocess invocations against the same run directory.

    Args:
        setup_fn: Creates the run and returns its directory path.
        contended_command: The command list both processes will execute.
        expected_winner_count: How many processes should succeed (exit code 0).
        timeout_seconds: Maximum time to wait for both processes.

    Returns:
        RaceResult with per-process stdout/stderr, exit codes, and final disk state.
    """
    # Create the run directory
    run_dir = setup_fn()

    # Use spawn to avoid macOS fork issues
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    output_queue = ctx.Queue()

    # Inherit current environment for subprocess children
    child_env = {**__import__("os").environ}

    p1 = ctx.Process(
        target=_run_and_capture,
        args=(barrier, output_queue, contended_command, child_env),
    )
    p2 = ctx.Process(
        target=_run_and_capture,
        args=(barrier, output_queue, contended_command, child_env),
    )

    p1_pid_val = 0
    p2_pid_val = 0

    try:
        p1.start()
        p2.start()

        p1_pid_val = p1.pid or 0
        p2_pid_val = p2.pid or 0

        p1.join(timeout=timeout_seconds)
        p2.join(timeout=timeout_seconds)

        if p1.is_alive():
            p1.terminate()
            p1.join(timeout=1.0)
        if p2.is_alive():
            p2.terminate()
            p2.join(timeout=1.0)
    finally:
        # Ensure processes are cleaned up
        if p1.is_alive():
            p1.kill()
        if p2.is_alive():
            p2.kill()

    # Collect results from queue
    results: list[dict[str, Any]] = []
    while not output_queue.empty():
        results.append(output_queue.get_nowait())

    # Sort by pid to ensure deterministic assignment
    results.sort(key=lambda r: r.get("pid") or 0)

    if len(results) == 0:
        # Both processes timed out or crashed before producing output
        return RaceResult(
            p1_pid=p1_pid_val,
            p2_pid=p2_pid_val,
            p1_exit_code=-1,
            p2_exit_code=-1,
            p1_stdout="",
            p1_stderr="",
            p2_stdout="",
            p2_stderr="",
            final_disk_state=_snapshot_disk_state(run_dir),
        )

    if len(results) == 1:
        # One process produced output; the other likely timed out
        r = results[0]
        return RaceResult(
            p1_pid=r.get("pid") or p1_pid_val,
            p2_pid=p2_pid_val,
            p1_exit_code=r.get("exit_code", -1),
            p2_exit_code=-1,
            p1_stdout=r.get("stdout", ""),
            p1_stderr=r.get("stderr", ""),
            p2_stdout="",
            p2_stderr="",
            final_disk_state=_snapshot_disk_state(run_dir),
        )

    r1, r2 = results[0], results[1]
    result = RaceResult(
        p1_pid=r1.get("pid") or p1_pid_val,
        p2_pid=r2.get("pid") or p2_pid_val,
        p1_exit_code=r1.get("exit_code", -1),
        p2_exit_code=r2.get("exit_code", -1),
        p1_stdout=r1.get("stdout", ""),
        p1_stderr=r1.get("stderr", ""),
        p2_stdout=r2.get("stdout", ""),
        p2_stderr=r2.get("stderr", ""),
        final_disk_state=_snapshot_disk_state(run_dir),
    )

    assert result.winner_count == expected_winner_count, (
        f"Expected {expected_winner_count} winner(s), got {result.winner_count}"
    )

    return result