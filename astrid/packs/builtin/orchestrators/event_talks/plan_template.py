"""Event-talks plan-template for Sprint 5b — emits a plan v2 for the four-step pipeline."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


def build_plan_v2(
    *,
    python_exec: str,
    run_root: str | Path,
    source: str | Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a plan v2 dict for the event_talks pipeline.

    Steps:
      ados-sunday-template → search-transcript → find-holding-screens → render

    All steps use ``adapter: local`` — the pipeline is pure local ffmpeg/OCR/static writes.
    Cost is $0 for all steps (no LLM or RunPod calls).
    """
    run_root = Path(run_root)
    plan_id = f"event-talks-{run_id or uuid.uuid4().hex[:12]}"

    cmd_ados = _build_ados_cmd(python_exec, run_root)
    cmd_search = _build_search_cmd(python_exec, run_root, source)
    cmd_holding = _build_holding_cmd(python_exec, run_root, source)
    cmd_render = _build_render_cmd(python_exec, run_root)

    plan: dict[str, Any] = {
        "plan_id": plan_id,
        "version": 2,
        "steps": [
            {
                "id": "ados-sunday-template",
                "adapter": "local",
                "command": cmd_ados,
                "produces": {
                    "template_output": {
                        "path": "ados-sunday-template.json",
                        "check": {
                            "check_id": "file_nonempty",
                            "params": {},
                            "sentinel": False,
                        },
                    }
                },
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
            {
                "id": "search-transcript",
                "adapter": "local",
                "command": cmd_search,
                "produces": {
                    "search_output": {
                        "path": "search-results.txt",
                        "check": {
                            "check_id": "file_nonempty",
                            "params": {},
                            "sentinel": False,
                        },
                    }
                },
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
            {
                "id": "find-holding-screens",
                "adapter": "local",
                "command": cmd_holding,
                "produces": {
                    "holding_output": {
                        "path": "holding-screens.json",
                        "check": {
                            "check_id": "file_nonempty",
                            "params": {},
                            "sentinel": False,
                        },
                    }
                },
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
            {
                "id": "render",
                "adapter": "local",
                "command": cmd_render,
                "produces": {
                    "render_output": {
                        "path": "render-manifest.json",
                        "check": {
                            "check_id": "file_nonempty",
                            "params": {},
                            "sentinel": False,
                        },
                    }
                },
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
            },
        ],
    }
    return plan


from astrid.core.orchestrator.plan_v2 import emit_plan_json  # noqa: F811 — shared helper


def _build_ados_cmd(python_exec: str, run_root: Path) -> str:
    out = run_root / "steps" / "ados-sunday-template" / "v1" / "produces"
    return (
        f"{python_exec} -m astrid.packs.builtin.orchestrators.event_talks.run "
        f"ados-sunday-template --out {out}"
    )


def _build_search_cmd(
    python_exec: str, run_root: Path, source: str | Path | None
) -> str:
    out = run_root / "steps" / "search-transcript" / "v1" / "produces"
    transcript = run_root / "steps" / "transcribe" / "v1" / "produces" / "transcript.json"
    src_flag = f"--transcript {transcript}" if source else ""
    return (
        f"{python_exec} -m astrid.packs.builtin.orchestrators.event_talks.run "
        f"search-transcript {src_flag} "
        f"> {out / 'search-results.txt'}"
    )


def _build_holding_cmd(
    python_exec: str, run_root: Path, source: str | Path | None
) -> str:
    out = run_root / "steps" / "find-holding-screens" / "v1" / "produces"
    src = str(Path(source).resolve()) if source else ""
    return (
        f"{python_exec} -m astrid.packs.builtin.orchestrators.event_talks.run "
        f"find-holding-screens --video {src} --out {out / 'holding-screens.json'}"
    )


def _build_render_cmd(python_exec: str, run_root: Path) -> str:
    out = run_root / "steps" / "render" / "v1" / "produces"
    manifest = run_root / "steps" / "ados-sunday-template" / "v1" / "produces" / "ados-sunday-template.json"
    return (
        f"{python_exec} -m astrid.packs.builtin.orchestrators.event_talks.run "
        f"render --manifest {manifest} --out-dir {out}"
    )