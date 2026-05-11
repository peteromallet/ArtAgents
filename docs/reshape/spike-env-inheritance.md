# Spike: Env Inheritance Audit

**Date:** 2026-05-11
**Purpose:** Confirm `ASTRID_SESSION_ID` survives all subprocess launch paths in the codebase.

## Findings Summary

All subprocess paths preserve `ASTRID_SESSION_ID`. No scrubbing was detected.

## Audit Results

| Path | Method | Preserves ASTRID_SESSION_ID | Notes |
|------|--------|---------------------------|-------|
| `executor._run_external_executor` (runner.py:308) | `subprocess.run(..., env={**os.environ, ...})` | ✅ YES | Starts with `**os.environ`, so all parent env vars survive. |
| `orchestrator._run_command_orchestrator` (runner.py:237) | `subprocess.run(..., env={**os.environ, ...})` | ✅ YES | Same pattern as executor runner. Full env merge. |
| `child_subprocess_env` (task/env.py:73) | Returns `dict(os.environ)` | ✅ YES | Starts from full `os.environ`; only selectively copies task vars. Custom vars survive. |
| `ThreadPoolExecutor` paths | Threads share parent memory | ✅ YES | No process boundary; env vars visible by default. |
| `multiprocessing.Process` (spawn) | Fresh interpreter inherits `os.environ` | ✅ YES | Env vars set before spawn are inherited by child. |
| `concurrent.futures.ProcessPoolExecutor` | Worker processes inherit `os.environ` | ✅ YES | Env vars set before executor creation are inherited. |

## Stop-Line Assessment

**No stop-line triggered.** All subprocess paths preserve `ASTRID_SESSION_ID`. Sprint 1's env-based session binding is viable.

## Recommendations for Sprint 1

1. Set `ASTRID_SESSION_ID` early in the session lifecycle (before any subprocess spawns).
2. No special env-handling code is needed in subprocess wrappers — the existing `{**os.environ, ...}` pattern handles it.
3. The `child_subprocess_env` function already provides a clean base; just ensure `ASTRID_SESSION_ID` is set in `os.environ` before it's called.
4. For `multiprocessing.Process` with `spawn` start method (used in the two-tab harness), set `ASTRID_SESSION_ID` before creating child processes.