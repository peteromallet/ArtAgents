"""Manual-adapter: out-of-band ack-driven OR inbox-driven completion."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from astrid.core.adapter import CompleteResult, DispatchResult, PollResult, RunContext
from astrid.core.task.plan import CostEntry, Step


def _step_dir(run_ctx: RunContext) -> Path:
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


# Inbox completion-entry contract — parity with the ack identity contract:
# every inbox-driven completion MUST carry submitted_by + submitted_by_kind.
REQUIRED_INBOX_KEYS = ("submitted_by", "submitted_by_kind")


class ManualAdapter:
    """Manual adapter — agent or human runs work out-of-band; completion arrives via ack or inbox."""

    name = "manual"

    def dispatch(self, step: Step, run_ctx: RunContext) -> DispatchResult:
        if step.command is None or not step.command.strip():
            return DispatchResult(status="rejected", reason="manual adapter requires a non-empty command (dispatch payload)")
        step_dir = _step_dir(run_ctx)
        step_dir.mkdir(parents=True, exist_ok=True)
        dispatch_path = step_dir / "dispatch.json"
        payload: dict[str, object] = {
            "step_id": step.id,
            "step_version": run_ctx.step_version,
            "command": step.command,
            "adapter": "manual",
            "assignee": step.assignee,
            "requires_ack": step.requires_ack,
            "dispatched_at": _utc_now_iso(),
        }
        if step.instructions is not None:
            payload["instructions"] = step.instructions
        if step.ack is not None:
            payload["ack"] = {"kind": step.ack.kind}
        dispatch_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return DispatchResult(status="dispatched", started_at=payload["dispatched_at"])  # type: ignore[arg-type]

    def poll(self, step: Step, run_ctx: RunContext) -> PollResult:
        completion = _read_completion(_step_dir(run_ctx))
        if completion is None:
            return PollResult(status="pending")
        return PollResult(status="done" if completion.get("status") != "failed" else "failed")

    def complete(self, step: Step, run_ctx: RunContext) -> CompleteResult:
        """Read produces/completion.json (inbox-driven path) OR rely on caller-supplied ack.

        cmd_next + the inbox consumer write produces/completion.json to this dir
        when an inbox entry routes here; ack-driven completion writes the same
        sidecar from cmd_ack. Either way the format is identical.
        """
        step_dir = _step_dir(run_ctx)
        completion = _read_completion(step_dir)
        if completion is None:
            return CompleteResult(status="failed", reason="manual completion not found")

        # Identity enforcement — parity with the ack identity contract.
        if completion.get("source") == "inbox":
            for key in REQUIRED_INBOX_KEYS:
                if not completion.get(key):
                    return CompleteResult(
                        status="failed",
                        reason=f"inbox completion missing required {key!r}",
                    )

        cost = _read_cost(completion)
        if completion.get("status") == "failed":
            return CompleteResult(status="failed", returncode=None, reason=str(completion.get("reason", "manual completion reported failure")), cost=cost)
        return CompleteResult(status="completed", cost=cost)


def _read_completion(step_dir: Path) -> dict[str, object] | None:
    candidate = step_dir / "produces" / "completion.json"
    if not candidate.exists():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _read_cost(payload: dict[str, object]) -> CostEntry | None:
    cost = payload.get("cost")
    if not isinstance(cost, dict):
        return None
    amount = cost.get("amount")
    currency = cost.get("currency")
    source = cost.get("source")
    if not isinstance(amount, (int, float)) or not isinstance(currency, str) or not isinstance(source, str):
        return None
    return CostEntry(amount=float(amount), currency=currency, source=source)
