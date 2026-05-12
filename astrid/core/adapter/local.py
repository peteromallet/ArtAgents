"""Local-adapter: subprocess-based execution (detach-capable so it outlives the tab)."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from astrid.core.adapter import CompleteResult, DispatchResult, PollResult, RunContext
from astrid.core.task.plan import CostEntry, Step


def _step_dir(run_ctx: RunContext) -> Path:
    """Resolve runs/<run>/steps/<id>/v<N>/[iterations|items]/... for this dispatch."""
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


class LocalAdapter:
    """Local subprocess adapter. Spawns detached so a closed tab does not kill the child."""

    name = "local"

    def dispatch(self, step: Step, run_ctx: RunContext) -> DispatchResult:
        if step.command is None or not step.command.strip():
            return DispatchResult(status="rejected", reason="local adapter requires a non-empty command")
        step_dir = _step_dir(run_ctx)
        step_dir.mkdir(parents=True, exist_ok=True)
        # Persist pid + start metadata so a re-attached session can poll.
        log_path = step_dir / "subprocess.log"
        meta_path = step_dir / "dispatch.json"

        # POSIX: start_new_session detaches from the controlling terminal so the
        # child survives the parent tab being closed.
        try:
            argv = shlex.split(step.command)
        except ValueError as exc:
            return DispatchResult(status="rejected", reason=f"command not shell-parseable: {exc}")

        log_handle = open(log_path, "ab")
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(run_ctx.project_root),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env={**os.environ},
            )
        except (FileNotFoundError, OSError) as exc:
            log_handle.close()
            return DispatchResult(status="rejected", reason=f"spawn failed: {exc}")
        finally:
            log_handle.close()

        started_at = _utc_now_iso()
        meta_path.write_text(
            json.dumps({"pid": proc.pid, "started_at": started_at, "command": step.command}),
            encoding="utf-8",
        )
        return DispatchResult(status="dispatched", pid=proc.pid, started_at=started_at)

    def poll(self, step: Step, run_ctx: RunContext) -> PollResult:
        meta_path = _step_dir(run_ctx) / "dispatch.json"
        if not meta_path.exists():
            return PollResult(status="pending")
        try:
            pid = int(json.loads(meta_path.read_text(encoding="utf-8")).get("pid", 0))
        except (json.JSONDecodeError, ValueError):
            return PollResult(status="failed")
        if pid <= 0:
            return PollResult(status="failed")
        # POSIX kill(pid, 0) probes process existence without sending a real signal.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            # Process exited; returncode unknown from a re-attached tab (orphaned).
            # complete() will infer status from produces-check + exit code if recorded.
            return PollResult(status="done")
        except PermissionError:
            # Process exists but not ours — treat as still running.
            return PollResult(status="running")
        return PollResult(status="running")

    def complete(self, step: Step, run_ctx: RunContext) -> CompleteResult:
        """Inspect produces + exit-code sidecar to classify completion."""
        step_dir = _step_dir(run_ctx)
        returncode_path = step_dir / "returncode"
        returncode: int | None = None
        if returncode_path.exists():
            try:
                returncode = int(returncode_path.read_text(encoding="utf-8").strip())
            except ValueError:
                returncode = None

        # Produces checks: every declared produces.path must exist (non-empty file).
        produces_root = step_dir / "produces"
        missing: list[str] = []
        for entry in step.produces:
            candidate = produces_root / entry.path
            if not candidate.exists() or candidate.stat().st_size == 0:
                missing.append(entry.path)

        cost = _read_cost_sidecar(step_dir)

        if returncode is not None and returncode != 0:
            return CompleteResult(
                status="failed",
                returncode=returncode,
                reason=f"subprocess exited with returncode={returncode}",
                cost=cost,
            )
        if missing:
            return CompleteResult(
                status="failed",
                returncode=returncode,
                reason=f"produces check failed: missing {missing!r}",
                cost=cost,
            )
        return CompleteResult(status="completed", returncode=returncode, cost=cost)


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
    if not isinstance(amount, (int, float)) or not isinstance(currency, str) or not isinstance(source, str):
        return None
    return CostEntry(amount=float(amount), currency=currency, source=source)
