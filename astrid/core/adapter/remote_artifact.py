"""Remote-artifact adapter — dispatches a remote job, polls, fetches artifacts with checksums."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from astrid.core.adapter import (
    CompleteResult,
    CompleteStatus,
    DispatchResult,
    PollResult,
    PollStatus,
    RunContext,
)
from astrid.core.adapter.remote_artifact_fetch import FetchResult, fetch_artifacts
from astrid.core.task.plan import CostEntry, Step


def _step_dir(run_ctx: RunContext) -> Path:
    """Resolve runs/<run>/steps/<id>/v<N>/... for this dispatch."""
    base = run_ctx.project_root / "runs" / run_ctx.run_id / "steps"
    for segment in run_ctx.plan_step_path:
        base = base / segment
    base = base / f"v{run_ctx.step_version}"
    if run_ctx.iteration is not None:
        base = base / "iterations" / f"{run_ctx.iteration:03d}"
    elif run_ctx.item_id is not None:
        base = base / "items" / run_ctx.item_id
    return base


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class RemoteArtifactAdapter:
    """Adapter for steps targeting a remote executor pack.

    ``dispatch()`` spawns the step's *command* (the executor pack invocation)
    as a detached subprocess and captures the remote job ID from its stdout.
    ``poll()`` checks subprocess liveness.  ``complete()`` verifies every
    declared artifact via :func:`fetch_artifacts` and returns ``awaiting_fetch``
    when any artifact is missing or has a checksum mismatch.
    """

    name = "remote-artifact"

    def dispatch(self, step: Step, run_ctx: RunContext) -> DispatchResult:
        if step.command is None or not step.command.strip():
            return DispatchResult(
                status="rejected",
                reason="remote-artifact adapter requires a non-empty command",
            )
        step_dir = _step_dir(run_ctx)
        step_dir.mkdir(parents=True, exist_ok=True)

        log_path = step_dir / "subprocess.log"

        try:
            argv = shlex.split(step.command)
        except ValueError as exc:
            return DispatchResult(
                status="rejected",
                reason=f"command not shell-parseable: {exc}",
            )

        log_handle = open(log_path, "ab")
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(run_ctx.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env={**os.environ},
            )
        except (FileNotFoundError, OSError) as exc:
            log_handle.close()
            return DispatchResult(
                status="rejected", reason=f"spawn failed: {exc}"
            )

        # Read the first stdout line as the remote job ID.
        started_at = _utc_now_iso()
        job_id: str | None = None
        try:
            if proc.stdout is not None:
                line = proc.stdout.readline()
                if line:
                    job_id = line.decode("utf-8", errors="replace").strip()
                    # Write captured line + remainder into log.
                    log_handle.write(line)
                    # Drain remaining stdout into log asynchronously via a copy loop.
                    # We launch a thread to tee stdout into the log.
                    import threading

                    def _tee_stdout() -> None:
                        if proc.stdout is None:
                            return
                        try:
                            for chunk in iter(lambda: proc.stdout.read(4096), b""):
                                log_handle.write(chunk)
                                log_handle.flush()
                        except (ValueError, OSError):
                            pass

                    threading.Thread(target=_tee_stdout, daemon=True).start()
        except Exception:
            pass
        finally:
            log_handle.close()

        # Persist remote state sidecar.
        poll_interval = getattr(step, "poll_interval_seconds", 30) or 30
        remote_state = {
            "job_id": job_id,
            "started_at": started_at,
            "command": step.command,
            "poll_interval_seconds": poll_interval,
            "pid": proc.pid,
        }
        (step_dir / "remote_state.json").write_text(
            json.dumps(remote_state), encoding="utf-8"
        )

        # Also write a returncode sidecar placeholder for the executor.
        (step_dir / "returncode").write_text("-1", encoding="utf-8")

        return DispatchResult(
            status="dispatched", pid=proc.pid, started_at=started_at
        )

    def poll(self, step: Step, run_ctx: RunContext) -> PollResult:
        remote_state_path = _step_dir(run_ctx) / "remote_state.json"
        if not remote_state_path.exists():
            return PollResult(status="pending")

        try:
            state = json.loads(remote_state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return PollResult(status="failed")

        pid = state.get("pid", 0)
        if pid is None or pid <= 0:
            return PollResult(status="failed")

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return PollResult(status="done")
        except PermissionError:
            return PollResult(status="running")
        return PollResult(status="running")

    def complete(self, step: Step, run_ctx: RunContext) -> CompleteResult:
        """Verify artifacts and classify completion.

        Returns ``awaiting_fetch`` when any produce is missing or has
        a checksum mismatch.  Returns ``failed`` only when the subprocess
        itself reported a non-zero exit.
        """
        step_dir = _step_dir(run_ctx)
        returncode_path = step_dir / "returncode"
        returncode: int | None = None
        if returncode_path.exists():
            try:
                returncode = int(returncode_path.read_text(encoding="utf-8").strip())
            except ValueError:
                returncode = None

        cost = _read_cost_sidecar(step_dir)

        # If the subprocess failed hard, fail the step.
        if returncode is not None and returncode != 0 and returncode != -1:
            return CompleteResult(
                status="failed",
                returncode=returncode,
                reason=f"subprocess exited with returncode={returncode}",
                cost=cost,
            )

        # Run artifact fetch + checksum verification.
        fetch_result: FetchResult = fetch_artifacts(step, run_ctx)

        if fetch_result.status == "completed":
            return CompleteResult(
                status="completed", returncode=returncode or 0, cost=cost
            )

        if fetch_result.status == "awaiting_fetch":
            # Persist missing/mismatched into remote_state.json so the gate's
            # record_dispatch_complete can read them via _read_awaiting_fetch_items.
            _persist_fetch_items(step_dir, fetch_result)
            return CompleteResult(
                status="awaiting_fetch",
                returncode=returncode,
                reason=fetch_result.reason,
                cost=cost,
            )

        return CompleteResult(
            status="failed",
            returncode=returncode,
            reason=fetch_result.reason,
            cost=cost,
        )


def _persist_fetch_items(step_dir: Path, fetch_result: FetchResult) -> None:
    """Write missing/mismatched artifact names into remote_state.json."""
    remote_state_path = step_dir / "remote_state.json"
    try:
        if remote_state_path.exists():
            state = json.loads(remote_state_path.read_text(encoding="utf-8"))
        else:
            state = {}
    except (json.JSONDecodeError, OSError):
        state = {}
    state["missing"] = fetch_result.missing
    state["mismatched"] = fetch_result.mismatched
    remote_state_path.write_text(json.dumps(state), encoding="utf-8")


def _read_cost_sidecar(step_dir: Path) -> CostEntry | None:
    """Honor the hype-spike G2 convention: subprocess MAY write produces/cost.json."""
    candidate = step_dir / "produces" / "cost.json"
    if not candidate.exists():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    amount = payload.get("amount")
    currency = payload.get("currency")
    source = payload.get("source")
    if (
        not isinstance(amount, (int, float))
        or not isinstance(currency, str)
        or not isinstance(source, str)
    ):
        return None
    return CostEntry(amount=float(amount), currency=currency, source=source)