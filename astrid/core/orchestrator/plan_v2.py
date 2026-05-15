"""Shared plan-v2 builder helpers for orchestrator plan templates.

Orchestrator scaffolds include a ``plan_template.py`` that imports from
this module.  Use these helpers to construct plan-v2 dicts, step commands,
and produces blocks without copy-pasting the same four-line emit function
into every pack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# TypedDicts for plan-v2 structure
# ---------------------------------------------------------------------------


class PlanStep(TypedDict, total=False):
    """A single step in a plan-v2 document."""

    id: str
    adapter: str
    command: str
    produces: dict[str, Any]
    cost: dict[str, Any]
    repeat: dict[str, Any]
    children: list["PlanStep"]


class PlanV2(TypedDict):
    """Top-level plan-v2 document."""

    plan_id: str
    version: int
    steps: list[PlanStep]


# ---------------------------------------------------------------------------
# emit_plan_json — the canonical JSON serialisation shared across packs
# ---------------------------------------------------------------------------


def emit_plan_json(plan: dict[str, Any], path: str | Path) -> None:
    """Write a plan dict as canonical JSON to *path*.

    Creates parent directories as needed.  Output is stable (sorted keys)
    so that plan hashes are reproducible.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(payload, encoding="utf-8")


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def build_step_command(
    python_exec: str,
    run_root: Path,
    step_id: str,
    module_path: str,
    *,
    extra_args: str = "",
) -> str:
    """Construct a canonical step command string.

    Produces a command following the ``{python_exec} -m <module>
    --out <run_root>/steps/<step_id>/v1/produces`` pattern used by
    the canonical runtime path.
    """
    out = run_root / "steps" / step_id / "v1" / "produces"
    cmd = f"{python_exec} -m {module_path} --out {out}"
    if extra_args:
        cmd += f" {extra_args}"
    return cmd


def make_produces(
    path: str, check_id: str = "file_nonempty"
) -> dict[str, Any]:
    """Return a minimal ``produces`` block for a plan step.

    Args:
        path: Relative path within ``produces/`` that the step writes.
        check_id: Check identifier (default ``"file_nonempty"``).

    Returns:
        A dict suitable for use as a ``produces`` value in a plan step.
    """
    return {
        path: {
            "path": path,
            "check": {
                "check_id": check_id,
                "params": {},
                "sentinel": False,
            },
        }
    }
