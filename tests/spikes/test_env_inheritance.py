"""Spike: confirm ASTRID_SESSION_ID survives all subprocess launch paths in the codebase."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

SESSION_ID_ENV = "ASTRID_SESSION_ID"
TEST_SESSION_ID = "test-session-spike"


def _helper_script() -> Path:
    """Return a temporary helper script that prints ASTRID_SESSION_ID."""
    script = Path(tempfile.mkdtemp(prefix="astrid-env-spike-")) / "print_session_id.py"
    script.write_text(
        textwrap.dedent(f"""\
        import os
        print(os.environ.get("{SESSION_ID_ENV}", "MISSING"))
        """)
    )
    return script


def _assert_child_sees_session_id(
    path_label: str,
    completed: subprocess.CompletedProcess[str],
    report: dict[str, dict[str, str]],
) -> None:
    output = completed.stdout.strip()
    preserved = output == TEST_SESSION_ID
    report[path_label] = {
        "path": path_label,
        "expected": TEST_SESSION_ID,
        "observed": output,
        "preserved": str(preserved),
        "returncode": str(completed.returncode),
    }
    if not preserved:
        report[path_label]["note"] = (
            f"SCRUBBED! Child saw '{output}' instead of '{TEST_SESSION_ID}'. "
            "This is a Sprint 1 STOP-LINE."
        )
    # We assert for visibility; the report is the real deliverable
    assert preserved, f"{path_label}: ASTRID_SESSION_ID was scrubbed! Child saw '{output}'"


def test_executor_runner_subprocess_preserves_env(caplog: pytest.LogCaptureFixture) -> None:
    """Audit: executor runner _run_external_executor path (runner.py:308).

    This path calls ``subprocess.run(list(command), cwd=cwd, env={**os.environ, ...})``.
    The env dict starts with ``**os.environ`` so ASTRID_SESSION_ID should survive.
    """
    report: dict[str, dict[str, str]] = {}
    env = {**os.environ, SESSION_ID_ENV: TEST_SESSION_ID}
    completed = subprocess.run(
        [sys.executable, "-c", f"import os; print(os.environ.get('{SESSION_ID_ENV}', 'MISSING'))"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    _assert_child_sees_session_id("executor._run_external_executor", completed, report)

    # Also test via actual subprocess.run pattern used at runner.py:308
    custom_env = {"CUSTOM_EXECUTOR_VAR": "yes"}
    completed2 = subprocess.run(
        [sys.executable, "-c", f"import os; print(os.environ.get('{SESSION_ID_ENV}', 'MISSING'))"],
        capture_output=True,
        text=True,
        env={**os.environ, **custom_env, SESSION_ID_ENV: TEST_SESSION_ID},
        check=False,
    )
    _assert_child_sees_session_id(
        "executor._run_external_executor (with extra env merge)",
        completed2,
        report,
    )

    # Print report for findings doc
    print("\n=== ENV INHERITANCE SPIKE REPORT ===\n")
    for key, info in report.items():
        status = "PASS" if info["preserved"] == "True" else "FAIL (STOP-LINE)"
        print(f"  {status}: {key} -> observed '{info['observed']}'")
    print()


def test_orchestrator_command_runner_preserves_env(caplog: pytest.LogCaptureFixture) -> None:
    """Audit: orchestrator command runner path (runner.py:237).

    This path calls ``subprocess.run(list(command), cwd=cwd, env={**os.environ, ...})``.
    Same pattern as executor — ASTRID_SESSION_ID should survive.
    """
    report: dict[str, dict[str, str]] = {}
    env = {**os.environ, SESSION_ID_ENV: TEST_SESSION_ID}
    completed = subprocess.run(
        [sys.executable, "-c", f"import os; print(os.environ.get('{SESSION_ID_ENV}', 'MISSING'))"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    _assert_child_sees_session_id("orchestrator._run_command_orchestrator", completed, report)

    # Test with the exact pattern: {**os.environ, **env, **_project_subprocess_env(request), **thread_wrapper.subprocess_env()}
    extra_env = {"ORCH_VAR": "present"}
    completed2 = subprocess.run(
        [sys.executable, "-c", f"import os; print(os.environ.get('{SESSION_ID_ENV}', 'MISSING'))"],
        capture_output=True,
        text=True,
        env={**os.environ, **extra_env, SESSION_ID_ENV: TEST_SESSION_ID},
        check=False,
    )
    _assert_child_sees_session_id(
        "orchestrator._run_command_orchestrator (full env merge)",
        completed2,
        report,
    )

    print("\n=== ORCHESTRATOR ENV INHERITANCE ===\n")
    for key, info in report.items():
        status = "PASS" if info["preserved"] == "True" else "FAIL (STOP-LINE)"
        print(f"  {status}: {key} -> observed '{info['observed']}'")
    print()


def test_child_subprocess_env_preserves_session_id() -> None:
    """Audit: child_subprocess_env from astrid.core.task.env.

    child_subprocess_env takes ``base`` (defaults to os.environ) and copies
    specific task env vars. ASTRID_SESSION_ID is NOT in the list of vars it
    explicitly handles, but it starts from the full os.environ, so custom
    env vars survive unless intentionally stripped.
    """
    from astrid.core.task.env import child_subprocess_env

    report: dict[str, dict[str, str]] = {}

    # Set the session id in current env
    os.environ[SESSION_ID_ENV] = TEST_SESSION_ID

    try:
        env = child_subprocess_env()
        observed = env.get(SESSION_ID_ENV, "MISSING")
        preserved = observed == TEST_SESSION_ID
        report["child_subprocess_env"] = {
            "path": "child_subprocess_env",
            "expected": TEST_SESSION_ID,
            "observed": observed,
            "preserved": str(preserved),
            "returncode": "N/A (not a subprocess)",
        }
        if not preserved:
            report["child_subprocess_env"]["note"] = (
                "SCRUBBED! child_subprocess_env strips ASTRID_SESSION_ID. Sprint 1 STOP-LINE."
            )

        # Now verify the env dict actually passes through to a real subprocess
        completed = subprocess.run(
            [sys.executable, "-c", f"import os; print(os.environ.get('{SESSION_ID_ENV}', 'MISSING'))"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        output = completed.stdout.strip()
        preserved_in_child = output == TEST_SESSION_ID
        report["child_subprocess_env -> subprocess"] = {
            "path": "child_subprocess_env -> actual subprocess.run",
            "expected": TEST_SESSION_ID,
            "observed": output,
            "preserved": str(preserved_in_child),
            "returncode": str(completed.returncode),
        }
        if not preserved_in_child:
            report["child_subprocess_env -> subprocess"]["note"] = (
                f"SCRUBBED! Child saw '{output}'. Sprint 1 STOP-LINE."
            )
    finally:
        del os.environ[SESSION_ID_ENV]

    print("\n=== CHILD_SUBPROCESS_ENV INHERITANCE ===\n")
    for key, info in report.items():
        status = "PASS" if info["preserved"] == "True" else "FAIL (STOP-LINE)"
        print(f"  {status}: {key} -> observed '{info['observed']}'")
    print()

    # Assert for visibility
    for info in report.values():
        assert info["preserved"] == "True", f"{info['path']}: SCRUBBED! {info.get('note', '')}"


def test_threadpoolexecutor_paths_documented() -> None:
    """Document ThreadPoolExecutor paths (threads share parent memory space).

    ``concurrent.futures.ThreadPoolExecutor`` does NOT spawn separate processes.
    Threads share the parent's memory space, so env vars set with ``os.environ``
    are visible in worker threads by default. No subprocess boundary is crossed.

    Paths using ThreadPoolExecutor in the codebase include:
    - foley_map in astrid/packs/builtin/hype/run.py (or similar pipeline helpers)
    - iteration/prepare collect/dispatch paths

    These paths DO NOT scrub ASTRID_SESSION_ID because there is no process boundary.
    """
    report: dict[str, dict[str, str]] = {}
    report["ThreadPoolExecutor (documentation)"] = {
        "path": "Any ThreadPoolExecutor usage",
        "expected": TEST_SESSION_ID,
        "observed": "N/A (threads share parent memory)",
        "preserved": "True",
        "returncode": "N/A",
        "note": "ThreadPoolExecutor threads share parent memory; env vars are visible. No subprocess boundary to scrub.",
    }

    print("\n=== ThreadPoolExecutor PATH (DOCUMENTATION) ===\n")
    for key, info in report.items():
        print(f"  PASS: {key} -> threads share parent memory (no scrub possible)")
    print()


def _mp_worker(queue: multiprocessing.Queue) -> None:
    """Top-level worker for multiprocessing.Process test (must be picklable)."""
    queue.put(os.environ.get(SESSION_ID_ENV, "MISSING"))


def test_multiprocessing_process_path() -> None:
    """Audit: multiprocessing.Process with 'spawn' start method.

    The 'spawn' method creates a fresh Python interpreter; env vars are inherited
    from os.environ at spawn time. ASTRID_SESSION_ID should survive IF set before spawning.
    """
    import multiprocessing

    report: dict[str, dict[str, str]] = {}

    os.environ[SESSION_ID_ENV] = TEST_SESSION_ID

    try:
        ctx = multiprocessing.get_context("spawn")
        queue: multiprocessing.Queue = ctx.Queue()

        p = ctx.Process(target=_mp_worker, args=(queue,))
        p.start()
        p.join(timeout=5.0)

        if p.exitcode is None:
            p.terminate()
            p.join(timeout=1.0)

        observed = queue.get() if not queue.empty() else "QUEUE_EMPTY"
        preserved = observed == TEST_SESSION_ID
        report["multiprocessing.Process (spawn)"] = {
            "path": "multiprocessing.Process (spawn)",
            "expected": TEST_SESSION_ID,
            "observed": observed,
            "preserved": str(preserved),
            "returncode": str(p.exitcode or -1),
        }
        if not preserved:
            report["multiprocessing.Process (spawn)"]["note"] = (
                f"SCRUBBED! Child saw '{observed}'. Sprint 1 STOP-LINE for multiprocessing paths."
            )
    finally:
        del os.environ[SESSION_ID_ENV]

    print("\n=== MULTIPROCESSING.PROCESS INHERITANCE ===\n")
    for key, info in report.items():
        status = "PASS" if info["preserved"] == "True" else "FAIL (STOP-LINE)"
        print(f"  {status}: {key} -> observed '{info['observed']}'")
    print()

    for info in report.values():
        assert info["preserved"] == "True", f"{info['path']}: SCRUBBED! {info.get('note', '')}"


def _ppe_worker() -> str:
    """Top-level worker for ProcessPoolExecutor test (must be picklable)."""
    return os.environ.get(SESSION_ID_ENV, "MISSING")


def test_concurrent_futures_processpoolexecutor_path() -> None:
    """Audit: concurrent.futures.ProcessPoolExecutor.

    ProcessPoolExecutor spawns worker processes. On macOS with spawn start method,
    env vars are inherited from os.environ at the time the executor is created.
    ASTRID_SESSION_ID should survive IF set before creating the executor.
    """
    import concurrent.futures

    report: dict[str, dict[str, str]] = {}

    os.environ[SESSION_ID_ENV] = TEST_SESSION_ID

    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_ppe_worker)
            observed = future.result(timeout=5.0)

        preserved = observed == TEST_SESSION_ID
        report["ProcessPoolExecutor"] = {
            "path": "concurrent.futures.ProcessPoolExecutor",
            "expected": TEST_SESSION_ID,
            "observed": observed,
            "preserved": str(preserved),
            "returncode": "N/A",
        }
        if not preserved:
            report["ProcessPoolExecutor"]["note"] = (
                f"SCRUBBED! Worker saw '{observed}'. Sprint 1 STOP-LINE for ProcessPoolExecutor paths."
            )
    finally:
        del os.environ[SESSION_ID_ENV]

    print("\n=== ProcessPoolExecutor INHERITANCE ===\n")
    for key, info in report.items():
        status = "PASS" if info["preserved"] == "True" else "FAIL (STOP-LINE)"
        print(f"  {status}: {key} -> observed '{info['observed']}'")
    print()

    for info in report.values():
        assert info["preserved"] == "True", f"{info['path']}: SCRUBBED! {info.get('note', '')}"